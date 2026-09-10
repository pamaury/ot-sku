# Copyright lowRISC contributors (OpenTitan project).
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

def _hub_repo_impl(rctx):
    for folder_name, spoke_file in rctx.attr.repo_mapping.items():
        # Get the absolute path to the spoke repository's root
        # using the label of a file in the root of the spoke repository.
        spoke_path = rctx.path(spoke_file).dirname

        # Symlink the entire spoke repo to a top-level folder in the hub
        rctx.symlink(spoke_path, folder_name)

    # Create a root BUILD file so Bazel recognizes these as packages
    rctx.file("BUILD.bazel", "# Hub Root")

hub_repo = repository_rule(
    implementation = _hub_repo_impl,
    attrs = {"repo_mapping": attr.string_keyed_label_dict(
        doc = "Map hub symlink names to spoke repositories.  The spoke repo should be the label of a file in the root of the spoke repo (e.g. BUILD.bazel)",
    )},
)

# Important note: this dictionary is read and modified by the release script (script/release.py).
# Therefore, it needs to remain a constant dictionary which can be parsed by the python ast module.
_ARCHIVES = {
    "presign_rom_ext": {
        "url": "https://github.com/pamaury/ot-sku/releases/download/presign-2026-09-10-test-1/presign_rom_ext.tar.xz",
        "sha256": "94b8401bf4882e12e94ed908a576969ab31898edd18c8cdb8eece5d10edc7b92",
    },
    "presign_perso": {
        "url": "https://github.com/pamaury/ot-sku/releases/download/presign-2026-09-10-test-1/presign_perso.tar.xz",
        "sha256": "66244c38e21b04d3ccb3ef541582b705029bbcf3a355c8fa153e799c969f0cfd",
    },
    "perso_release": {
        "url": "https://github.com/pamaury/ot-sku/releases/download/final-release-2026-09-10-test-1/perso_release.tar.xz",
        "sha256": "5c2518f10a472149147cfc00d4593607b2377f5d8ebcfe6ea077d2d4ab0f6ea8",
    },
    "rom_ext_release": {
        "url": "https://github.com/pamaury/ot-sku/releases/download/final-release-2026-09-10-test-1/rom_ext_release.tar.xz",
        "sha256": "a9f05eea5dc1111bedb8b8ca0c51ee1074e02d59ff5b4a783b55c459d635aa9c",
    },
}

def _extra_impl(mctx):
    for (name, info) in _ARCHIVES.items():
        http_archive(
            name = name,
            **info
        )
    hub_repo(
        name = "provisioning_exts_extra",
        repo_mapping = {
            name: "@{}//:BUILD.bazel".format(name)
            for name in _ARCHIVES
        },
    )

extra = module_extension(
    implementation = _extra_impl,
)
