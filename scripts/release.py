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
        print(f"debug: {msg}")


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


def cquery_path(pargs, label):
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


ARCHIVES_EXTENSIONS = [
    ".zip", ".tar.xz",
]


ARTIFACTS = {
    "perso": {
        "presign_label": "@provisioning_exts//open/perso:presign_perso",
        "presign_name": ("presign_perso", ARCHIVES_EXTENSIONS),
        "presign_ext_repo": "presign_perso",
        "sig_name": ("perso_sig", ARCHIVES_EXTENSIONS),
        "sig_extract_dir": Path("skus") / "open" / "signatures" / "perso",
        "sig_test_label": "@provisioning_exts//open/perso:signature_test",
        "release_label": "@provisioning_exts//open/perso:perso_release",
        "release_name": ("perso_release", ARCHIVES_EXTENSIONS),
        "release_ext_repo": "perso_release",
    },
    "rom_ext": {
        "presign_label": "@provisioning_exts//open/rom_ext:presign_rom_ext",
        "presign_name": ("presign_rom_ext", ARCHIVES_EXTENSIONS),
        "presign_ext_repo": "presign_rom_ext",
        "sig_name": ("rom_ext_sig", ARCHIVES_EXTENSIONS),
        "sig_extract_dir": Path("skus") / "open" / "signatures" / "rom_ext",
        "sig_test_label": "@provisioning_exts//open/rom_ext:signature_test",
        "release_label": "@provisioning_exts//open/rom_ext:rom_ext_release",
        "release_name": ("rom_ext_release", ARCHIVES_EXTENSIONS),
        "release_ext_repo": "rom_ext_release",
    },
}


def asset_name_pattern(asset_name):
    name, exts = asset_name
    if not exts:
        return name
    if len(exts) == 1:
        return name + exts[0]
    return name + "{" + ",".join(exts) + "}"


def create_presign_release(pargs):
    # Check if a release already exists.
    release_list = run_gh_or_exit(pargs, "cannot query release list", [
        "release", "list", "-L", "1000"]).decode('utf-8').split()
    # The format of each line of the output is:
    # <tag> ...
    if any(release.split()[0] == pargs.tag for release in release_list):
        print_info(pargs, f"release {pargs.tag} already exists, skipping build")
        return

    artifact_labels = [
        ARTIFACTS[art]["presign_label"]
        for art in pargs.release_artifacts
    ]
    # Build the artifacts.
    run_or_exit(pargs, "cannot build provisioning artifacts", [
        pargs.bazelisk, "build"] + pargs.bazel_opts + [
        "--stamp"] + artifact_labels,
        cwd=pargs.ot_repo,
    )

    # Obtain absolute paths to the artefacts.
    binaries = [cquery_path(pargs, label) for label in artifact_labels]

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
    ] + binaries,  # Binaries to release
    )


def parse_json(pargs, asset_msg, json_str):
    try:
        return json.loads(json_str)
    except Exception as e:
        print_error(pargs, f"cannot parse JSON of {asset_msg}")
        print_group(pargs, "error", e)
        print_group(pargs, "content info", json_str)
        sys.exit(1)


def get_release_info(pargs):
    # Get asset information so that we can update the archives in the extension.
    release_info = run_gh_or_exit(pargs, "cannot query release assets", [
        "release", "view", pargs.tag, "--json", "assets,targetCommitish"])
    return parse_json(pargs, "release asset", release_info)


def target_commitish_to_sha(pargs, commitish):
    return run_or_exit(
        pargs,
        "cannot retrieve release target SHA",
        [pargs.gh_bin, "api", "-H", "Accept: application/vnd.github.sha",
         f"repos/{pargs.release_repo}/commits/{commitish}"],
    ).decode('utf-8').strip()


def asset_name_match(candidate_name, asset_name_constraint):
    asset_name, allowed_exts = asset_name_constraint
    for ext in allowed_exts:
        if candidate_name.endswith(ext) and candidate_name.removesuffix(ext) == asset_name:
            return True
    return False


def get_release_asset_info(pargs, release_info, asset_names, allow_no_match=False):
    res = {}
    for (key, asset_name) in asset_names.items():
        assets = [
            asset
            for asset in release_info["assets"]
            if asset_name_match(asset["name"], asset_name)
        ]
        if len(assets) == 0:
            if allow_no_match:
                # Skip this item
                continue
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
        res[key] = parse_json(pargs, "release asset", asset_info)
    return res


def decode_github_integrity(digest):
    # FIXME The digest format of Github does not seem to be documented.
    # Experimentally, it seems to be 'sha256:<hash>'
    assert digest.startswith('sha256:'), 'release asset digest does not use SHA256'
    return {
        'sha256': digest.removeprefix('sha256:')
    }


def create_branch(pargs, orig_ref_sha, branch_name):
    # Create a branch on github at original ref.
    run_or_exit(
        pargs,
        f"cannot create branch {branch_name} on github",
        [pargs.gh_bin, "api", "--method", "POST",
         f"repos/{pargs.release_repo}/git/refs",
         "-f", f"ref=refs/heads/{branch_name}",
         "-f", f'sha={orig_ref_sha}'],
    )


def get_file_content(pargs, ref, filename):
    file_info = run_or_exit(
        pargs,
        f"cannot retrieve the content of {filename}",
        [pargs.gh_bin, "api",
         f"repos/{pargs.release_repo}/contents/{filename}?ref={ref}"],
    ).decode('utf-8')
    return parse_json(pargs, "file info", file_info)


def push_commit(pargs, branch_name, commit_msg, file_info, content):
    filename = file_info["path"]
    run_or_exit(
        pargs,
        f"cannot push commit to branch {branch_name} on github",
        [pargs.gh_bin, "api", "--method", "PUT",
         f"repos/{pargs.release_repo}/contents/{filename}",
         "-f", f"message={commit_msg}",
         "-f", f"branch={branch_name}",
         "-f", "sha={}".format(file_info["sha"]),
         "-f", b"content=" + base64.b64encode(content),
         ],
    )


def create_presign_branch(pargs):
    # Important note:
    # this entire function is written in such a way that it does not need git
    # access. It only requires access the github API through `gh`.

    # Get asset information so that we can update the archives in the extension.
    release_info = get_release_info(pargs)

    # Convert release target into a SHA.
    release_sha = target_commitish_to_sha(pargs, release_info["targetCommitish"])

    # Get asset information.
    artifact_info = get_release_asset_info(
        pargs, release_info, {
            ARTIFACTS[art]["presign_ext_repo"]: ARTIFACTS[art]["presign_name"]
            for art in pargs.release_artifacts
        }
    )

    branch_name = pargs.tag
    # Create a release branch
    create_branch(pargs, release_sha, branch_name)

    # Get the content of the original extension file.
    orig_extension_bzl = get_file_content(pargs, release_sha, "extension.bzl")

    # Generate a modified extension file.
    new_extension_bzl = modify_extension_bzl(
        pargs,
        base64.b64decode(orig_extension_bzl["content"]).decode('utf-8'),
        {
            repo: {
                "url": art_info["browser_download_url"],
            } | decode_github_integrity(art_info['digest'])
            for (repo, art_info) in artifact_info.items()
        }
    ).encode('utf-8')

    # Push a commit to the branch.
    push_commit(
        pargs, branch_name,
        f"Update archives for presign release {pargs.tag}",
        orig_extension_bzl, new_extension_bzl
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
                print_debug(pargs, f"ignoring file {entry.filename} because it does not pass the filter")  # noqa:E501
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
    info_sig = get_release_asset_info(
        pargs, release_info, {
            art: ARTIFACTS[art]["sig_name"] for art in pargs.release_artifacts
        },
        allow_no_match=True,
    )
    sig_archives = {
        art: download_asset(pargs, info)
        for (art, info) in info_sig.items()
    }

    if not sig_archives:
        print_error(pargs, "none of the requested artifacts have signatures in the release")
        for art in pargs.release_artifacts:
            print_error(pargs, "for {}, upload a file named {} in the release".format(
                art, asset_name_pattern(ARTIFACTS[art]["sig_name"])
            ))
        sys.exit(1)
    else:
        print_info(pargs, "the following artifacts have signatures and will be released: {}".format(
            ",".join(list(sig_archives.keys()))
        ))

    # Extract archive content at the right place.
    def filter_only_sig(fname):
        return fname.endswith(".ecdsa_sig") or fname.endswith(".spx_sig")
    for (art, archive) in sig_archives.items():
        extract_archive(
            pargs,
            archive,
            pargs.ot_sku_repo / ARTIFACTS[art]["sig_extract_dir"],
            filter_only_sig,
        )

    # Run a signature test check.
    run_or_exit(pargs, "cannot verify the signatures", [
        pargs.bazelisk, "test"] + pargs.bazel_opts + [
        "--test_output=streamed"] + [
            ARTIFACTS[art]["sig_test_label"] for art in sig_archives],
        cwd=pargs.ot_repo,
    )

    artifact_labels = [
        ARTIFACTS[art]["release_label"]
        for art in sig_archives
    ]
    # Build the artifacts.
    run_or_exit(pargs, "cannot build provisioning artifacts", [
        pargs.bazelisk, "build"] + pargs.bazel_opts + [
        "--stamp"] + artifact_labels,
        cwd=pargs.ot_repo,
    )

    # Obtain absolute paths to the artefacts.
    binaries = [cquery_path(pargs, label) for label in artifact_labels]

    # Upload artifacts to the release.
    run_gh_or_exit(pargs, "cannot create release", [
        "release",
        "upload",
        # Release tag
        pargs.tag,
        # Binaries to release
    ] + binaries)


def create_postsign_pr(pargs):
    # Important note:
    # this entire function is written in such a way that it does not need git
    # access. It only requires access the github API through `gh`.

    # Get asset information so that we can update the archives in the extension.
    release_info = get_release_info(pargs)

    # Get the SHA of the release branch.
    release_branch_sha = target_commitish_to_sha(pargs, pargs.tag)

    # Get asset information.
    artifact_info = get_release_asset_info(
        pargs, release_info, {
            ARTIFACTS[art]["presign_ext_repo"]: ARTIFACTS[art]["presign_name"]
            for art in pargs.release_artifacts
        } | {
            ARTIFACTS[art]["release_ext_repo"]: ARTIFACTS[art]["release_name"]
            for art in pargs.release_artifacts
        },
        allow_no_match=True,
    )

    # Create a temporary branch for the PR.
    pr_branch_name = f"{pargs.tag}-pr"
    create_branch(pargs, release_branch_sha, pr_branch_name)

    # Get the content of the original extension file.
    orig_extension_bzl = get_file_content(pargs, release_branch_sha, "extension.bzl")

    # Generate a modified extension file.
    new_extension_bzl = modify_extension_bzl(
        pargs,
        base64.b64decode(orig_extension_bzl["content"]).decode('utf-8'),
        {
            repo: {
                "url": art_info["browser_download_url"],
            } | decode_github_integrity(art_info['digest'])
            for (repo, art_info) in artifact_info.items()
        }
    ).encode('utf-8')

    # Push a commit to the branch.
    push_commit(
        pargs, pr_branch_name,
        "Update archives for release",
        orig_extension_bzl, new_extension_bzl
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
    artiflist = ','.join(list(ARTIFACTS.keys()))
    parser.add_argument(
        '--release-artifacts',
        help="Comma separated list of artifacts to release (default is all, valid: {artiflist})",
        default=artiflist,
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

    # Parse artifacts list.
    args.release_artifacts = list(set(args.release_artifacts.split(',')))
    if invalid := [art for art in args.release_artifacts if art not in ARTIFACTS.keys()]:
        print_error(args, "invalid artifact: {}".format(invalid[0]))
        sys.exit(1)

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
        repo_info = parse_json(args, "repository info", repo_info)
        args.release_repo = repo_info["nameWithOwner"]

    if args.pre_sign:
        create_presign_release(args)
        create_presign_branch(args)
    if args.post_sign:
        create_postsign_release(args)
        create_postsign_pr(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
