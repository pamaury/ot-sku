#!/usr/bin/env python3
# Copyright lowRISC contributors (OpenTitan project).
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

import argparse
import ast
import base64
import io
import json
import subprocess
import sys
import zipfile

from pathlib import Path


def print_info(pargs, msg):
    if pargs.gha_console:
        print(f"::notice::{msg}")
    else:
        print(f"info: {msg}")


def print_error(pargs, msg):
    if pargs.gha_console:
        print(f"::error::{msg}")
    else:
        print(f"error: {msg}")


def print_debug(pargs, msg):
    if not msg or pargs.verbose < 1:
        return
    if pargs.gha_console:
        print(f"::debug::{msg}")
    else:
        print(f"error: {msg}")


def print_group(pargs, name, content):
    if not content:
        return
    if pargs.gha_console:
        print(f"::group::{name}")
        print(content)
        print("::endgroup::")
    else:
        print(f"==== {name} ====")
        print(content)
        print("===============")


def modify_extension_bzl(pargs, extension_bzl, archives):
    extension_ast = ast.parse(extension_bzl)
    # Look for an assignment to '_ARCHIVES'
    archives_assign = None
    for stmt in extension_ast.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and stmt.targets[0].id == '_ARCHIVES':  # noqa:E501
            archives_assign = stmt
    if not archives_assign:
        print_error(pargs, "could not find assignement to _ARCHIVES in extension.bzl")
        sys.exit(1)
    # Use the AST info to remove the old assignment and create a new one.
    extension_bzl = extension_bzl.splitlines(True)
    extension_bzl[archives_assign.lineno - 1:archives_assign.end_lineno] = \
        "_ARCHIVES = " + json.dumps(archives, indent="    ") + "\n"

    return ''.join(extension_bzl)


def run_or_exit(pargs, msg, *args, **kwargs):
    kwargs["capture_output"] = True
    print_debug(pargs, f"running: {args}")
    res = subprocess.run(
        *args,
        **kwargs,
    )
    print_debug(pargs, f"return code is {res.returncode}")
    print_debug(pargs, res.stderr.decode(errors='replace'))
    if res.returncode != 0:
        print_error(pargs, msg)
        print_group(pargs, "stderr", res.stderr.decode(errors='replace'))
        sys.exit(1)
    return res.stdout


def run_gh_or_exit(pargs, msg, cmd):
    pre_cmd = [pargs.gh_bin]
    if pargs.release_repo:
        pre_cmd.extend(["-R", pargs.release_repo])
    return run_or_exit(pargs, msg, pre_cmd + cmd, cwd=pargs.ot_sku_repo)


def check_repo_clean(pargs, repo_name, repo_path):
    # Make sure that git repository is clean.
    run_or_exit(
        pargs,
        f"cannot create a release because the {repo_name} repository is not clean",
        ["git", "diff-index", "--exit-code", "HEAD"],
        cwd=repo_path,
    )


def create_presign_release(pargs):
    # Check if a release already exists.
    release_list = run_gh_or_exit(pargs, "cannot query release list", [
        "release", "list", "-L", "1000"]).decode('utf-8').split()
    # The format of each line of the output is:
    # <tag> ...
    if any(release.split()[0] == pargs.tag for release in release_list):
        print_info(pargs, f"release {pargs.tag} already exists, skipping build")
        return

    # Build the presign perso firmware and rom_ext
    run_or_exit(pargs, "cannot build provisioning artifacts", [
        pargs.bazelisk, "build"] + pargs.bazel_opts + [
        "--stamp",
        "@provisioning_exts//open/perso:presign_perso",
        "@provisioning_exts//open/rom_ext:presign_rom_ext"],
        cwd=pargs.ot_repo,
    )

    # Obtain absolute paths to the artefacts.
    def cquery_path(label):
        output = run_or_exit(
            pargs,
            "bazel cquery failed",
            [pargs.bazelisk, "cquery", "--output=files"] + pargs.bazel_opts + [label],
            cwd=pargs.ot_repo,
        ).decode('utf-8').splitlines()
        if len(output) != 1:
            print_error(pargs, "bazel cquery output has unexpected format:")
            print_group(pargs, "cquery output", output)
            sys.exit(1)
        return (pargs.ot_repo / Path(output[0])).resolve()
    presign_perso = cquery_path("@provisioning_exts//open/perso:presign_perso")
    presign_rom_ext = cquery_path("@provisioning_exts//open/rom_ext:presign_rom_ext")

    # Create release.
    run_gh_or_exit(pargs, "cannot create release", [
        "release",
        "create",
        # Pre-release.
        "-p",
        # Use tag as release notes if none is provided.
        "-n", pargs.release_notes or pargs.tag,
        # Use tag as title if none is provided.
        "-t", pargs.release_title or pargs.tag,
        # Release tag
        pargs.tag,
        # Binaries to release
        presign_perso,
        presign_rom_ext
    ])


def get_release_info(pargs):
    # Get asset information so that we can update the archives in the extension.
    release_info = run_gh_or_exit(pargs, "cannot query release assets", [
        "release", "view", pargs.tag, "--json", "assets,targetCommitish"])
    try:
        return json.loads(release_info)
    except Exception as e:
        print_error(pargs, "cannot parse release asset JSON")
        print_group(pargs, "error", e)
        print_group(pargs, "release info", release_info)
        sys.exit(1)


def target_commitish_to_sha(pargs, commitish):
    return run_or_exit(
        pargs,
        "cannot retrieve release target SHA",
        [pargs.gh_bin, "api", "-H", "Accept: application/vnd.github.sha",
         f"repos/{pargs.release_repo}/commits/{commitish}"],
    ).decode('utf-8').strip()


ARCHIVES_EXTENSIONS = [
    ".zip", ".tar.xz",
]


def asset_name_match(candidate_name, asset_name_constraint):
    asset_name, allowed_exts = asset_name_constraint
    for ext in allowed_exts:
        if candidate_name.endswith(ext) and candidate_name.removesuffix(ext) == asset_name:
            return True
    return False


def get_release_asset_info(pargs, release_info, asset_names):
    res = []
    for asset_name in asset_names:
        assets = [
            asset
            for asset in release_info["assets"]
            if asset_name_match(asset["name"], asset_name)
        ]
        if len(assets) == 0:
            print_error(pargs, f"no asset matching {asset_name} in release {pargs.tag}")
            sys.exit(1)
        if len(assets) > 1:
            print_error(pargs, f"more than one asset matching {asset_name} in release {pargs.tag}")
            sys.exit(1)
        asset_info = run_or_exit(
            pargs,
            "cannot query asset info",
            [pargs.gh_bin, "api", assets[0]["apiUrl"]]
        )
        try:
            res.append(json.loads(asset_info))
        except Exception as e:
            print_error(pargs, "cannot parse release asset info JSON")
            print_group(pargs, "error", e)
            print_group(pargs, "asset info", asset_info)
            sys.exit(1)
    return tuple(res)


def create_branch(pargs):
    # Important note:
    # this entire function is written in such a way that it does not need git
    # access. It only requires access the github API through `gh`.

    # Get asset information so that we can update the archives in the extension.
    release_info = get_release_info(pargs)

    # Convert release target into a SHA.
    release_sha = target_commitish_to_sha(pargs, release_info["targetCommitish"])

    # Get asset information.
    presign_perso_info, presign_rom_ext_info = get_release_asset_info(
        pargs, release_info,
        [
            ('presign_perso', ARCHIVES_EXTENSIONS),
            ('presign_rom_ext', ARCHIVES_EXTENSIONS),
        ]
    )

    def integrity(digest):
        # FIXME The digest format of Github does not seem to be documented.
        # Experimentally, it seems to be 'sha256:<hash>'
        assert digest.startswith('sha256:'), 'release asset digest does not use SHA256'
        return {
            'sha256': digest.removeprefix('sha256:')
        }

    # Download the content of the extension.bzl file at the release.
    orig_extension_bzl = run_or_exit(
        pargs,
        "cannot retrieve the content of extension.bzl",
        [pargs.gh_bin, "api",
         f"repos/{pargs.release_repo}/contents/extension.bzl?ref={release_sha}"],
    ).decode('utf-8')
    try:
        orig_extension_bzl = json.loads(orig_extension_bzl)
    except Exception as e:
        print_error(pargs, "cannot parse content asset info JSON")
        print_group(pargs, "error", e)
        print_group(pargs, "content info", orig_extension_bzl)
        sys.exit(1)

    # Generate a modified MODULE.bazel file.
    new_extension_bzl = modify_extension_bzl(
        pargs,
        base64.b64decode(orig_extension_bzl["content"]).decode('utf-8'),
        {
            'presign_perso': {
                'url': presign_perso_info['browser_download_url'],
            } | integrity(presign_perso_info['digest']),
            'presign_rom_ext': {
                'url': presign_rom_ext_info['browser_download_url'],
            } | integrity(presign_rom_ext_info['digest']),
        }
    ).encode('utf-8')

    # Create a branch on github at the newly created commit.
    run_or_exit(
        pargs,
        "cannot create a branch on github",
        [pargs.gh_bin, "api", "--method", "POST",
         f"repos/{pargs.release_repo}/git/refs",
         "-f", f"ref=refs/heads/{pargs.tag}",
         "-f", f'sha={release_sha}'],
    )

    # Create a commit on github with the updated extension.bzl
    run_or_exit(
        pargs,
        "cannot push commit to branch on github",
        [pargs.gh_bin, "api", "--method", "PUT",
         f"repos/{pargs.release_repo}/contents/extension.bzl",
         "-f", f"message=Update archives for presign release {pargs.tag}",
         "-f", f"branch={pargs.tag}",
         "-f", "sha={}".format(orig_extension_bzl["sha"]),
         "-f", b"content=" + base64.b64encode(new_extension_bzl),
         ],
    )


def download_asset(pargs, asset_info):
    asset = run_or_exit(
        pargs,
        "cannot retrieve asset",
        [pargs.gh_bin, "api", "-H", "Accept: application/octet-stream",
         asset_info["url"]]
    )
    # TODO verify hash?
    return asset


def compute_common_subdir(pargs, infolist):
    subdir = None
    for entry in infolist:
        # Ignore directories
        if entry.is_dir():
            continue
        this_subdir = Path(entry.filename).parent
        subdir = subdir or this_subdir
        if subdir != this_subdir:
            print_error(pargs, "all files in the archives must be the same subdirectory")
            print_error(pargs, f"previous file was in {subdir}")
            print_error(pargs, f"current file is in {this_subdir}")
            sys.exit(1)
    return subdir or Path("")


def extract_archive(pargs, archive_bytes, out_dir, filter_fn):
    # TODO: handle tar files as well?
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes), "r")
        # Automatically handle the case where all files are in a subdirectory.
        ignore_prefix = compute_common_subdir(pargs, zf.infolist())
        # Extract all files which match
        for entry in zf.infolist():
            # Ignore directories
            if entry.is_dir():
                continue
            if not filter_fn(entry.filename):
                print_debug(pargs, f"ignoring file {entry.filename} because it does not pass the filter")  ## noqa:E501
                continue
            out_path = out_dir / (Path(entry.filename).relative_to(ignore_prefix))
            print_debug(pargs, f"extracting {entry.filename} to {out_path}")
            with zf.open(entry) as f:
                out_path.write_bytes(f.read())
    except Exception as e:
        print_error(pargs, f"cannot extract archive to {out_dir}")
        print_group(pargs, "error", e)
        sys.exit(1)


def create_postsign_release(pargs):
    # Get asset information so that we can update the archives in the extension.
    release_info = get_release_info(pargs)

    # TODO: check that repository SHAs match the pre-sign release SHAs?

    # Get signature assets.
    perso_sig, rom_ext_sig = get_release_asset_info(
        pargs, release_info,
        [
            ('perso_sig', ARCHIVES_EXTENSIONS),
            ('rom_ext_sig', ARCHIVES_EXTENSIONS),
        ]
    )
    perso_sig_archive = download_asset(pargs, perso_sig)
    rom_ext_sig_archive = download_asset(pargs, rom_ext_sig)

    # Extract archive content at the right place.
    def filter_only_sig(fname):
        return fname.endswith(".ecdsa_sig") or fname.endswith(".spx_sig")
    extract_archive(
        pargs,
        perso_sig_archive,
        pargs.ot_sku_repo / "skus" / "open" / "signatures" / "perso/",
        filter_only_sig,
    )
    extract_archive(
        pargs,
        rom_ext_sig_archive,
        pargs.ot_sku_repo / "skus" / "open" / "signatures" / "rom_ext/",
        filter_only_sig,
    )

    # Run a signature test check.
    run_or_exit(pargs, "cannot verify the signatures", [
        pargs.bazelisk, "test"] + pargs.bazel_opts + [
        "--test_output=streamed",
        "@provisioning_exts//open/rom_ext:signature_test",
        "@provisioning_exts//open/perso:signature_test"],
        cwd=pargs.ot_repo,
    )


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--gh-bin',
        default="gh",
        type=Path,
        help="path to the gh binary (default is to search in PATH)",
    )
    parser.add_argument(
        '--bazel-bin',
        default="bazelisk",
        type=Path,
        help="path to the bazel/bazelisk binary to be used in the ot-sku repository " +
        "(default is bazelisk, do NOT use OT bazelisk.sh!)",
    )
    parser.add_argument(
        '--ot-sku-repo',
        default=Path(__file__).parents[1],
        type=Path,
        help="path to the ot-sku repository (default is derived from the script path)",
    )
    parser.add_argument(
        '--ot-repo',
        type=Path,
        required=True,
        help="path to the opentitan repository",
    )
    parser.add_argument(
        '--release-notes',
        help="Github release notes (default is tag)",
    )
    parser.add_argument(
        '--release-title',
        help="Github release notes (default is tag)",
    )
    parser.add_argument(
        '--release-repo',
        help="Github release repository (default is the same as ot-sku)",
    )
    parser.add_argument(
        'tag',
        metavar='TAG',
        help="Release tag",
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='count',
        default=0,
        help="increasing verbosity level",
    )
    parser.add_argument(
        '--gha-console',
        action='store_true',
        help="add Github action specific console workflow commands for debug/error messages",
    )
    parser.add_argument(
        '--skip-git-clean',
        action='store_true',
        help="skip checks that opentitan/ot-sku repositories are clean (development only)",
    )
    step_group = parser.add_mutually_exclusive_group(required=True)
    step_group.add_argument(
        '--pre-sign',
        action='store_true',
        help="Perform pre-signing steps"
    )
    step_group.add_argument(
        '--post-sign',
        action='store_true',
        help="Perform post-signing steps"
    )
    args = parser.parse_args()
    # Resolve some paths since we are going to change the current directory.
    # Also do some sanity checks.
    args.ot_sku_repo = args.ot_sku_repo.resolve()
    if not (args.ot_sku_repo / 'MODULE.bazel').exists() or not (args.ot_sku_repo / 'extension.bzl').exists():  # noqa:E501
        print_error(args, f"{args.ot_sku_repo} does not seem to point to the ot-sku repository")
        sys.exit(1)
    args.ot_repo = args.ot_repo.resolve()
    if not (args.ot_repo / 'MODULE.bazel').exists() or not (args.ot_repo / 'bazelisk.sh').exists():
        print_error(args, f"{args.ot_sku_repo} does not seem to point to the opentitan repository")
        sys.exit(1)

    # Options to use when running bazel
    args.bazelisk = args.ot_repo / 'bazelisk.sh'
    args.bazel_opts = [
        f"--override_module=ot_provisioning_exts={args.ot_sku_repo}",
    ]

    # Make sure that git repositories are clean.
    if not args.skip_git_clean:
        check_repo_clean(args, "ot-sku", args.ot_sku_repo)
        check_repo_clean(args, "opentitan", args.ot_repo)

    # Find the name of the current repository if none was provided:
    if not args.release_repo:
        repo_info = run_gh_or_exit(
            args, "cannot query repository information",
            ["repo", "view", "--json", "nameWithOwner"],
        ).decode('utf-8')
        try:
            repo_info = json.loads(repo_info)
        except Exception as e:
            print_error(args, "cannot parse repository information JSON")
            print_group(args, "error", e)
            print_group(args, "content info", repo_info)
            sys.exit(1)
        args.release_repo = repo_info["nameWithOwner"]

    if args.pre_sign:
        create_presign_release(args)
        create_branch(args)
    if args.post_sign:
        create_postsign_release(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
