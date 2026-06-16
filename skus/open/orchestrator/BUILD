# Copyright lowRISC contributors (OpenTitan project).
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

package(default_visibility = ["//visibility:public"])

load(
    "@lowrisc_opentitan//rules:sku.bzl",
    "sku_cert",
    "sku_cfg",
)

# Benchtop provisioning orchestrator configuration files.
exports_files(glob(["**"]))

sku_cert(
    name = "fake_dica_ca",
    certificate = "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:dice_ca.pem",
    key_file = "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:sk.pkcs8.der",
    key_id = "0xfe584ae7_53790cfd_8601a312_fb32d3c1_b822d112",
    key_type = "Raw",
)

sku_cert(
    name = "fake_ext_ca",
    certificate = "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:ext_ca.pem",
    key_file = "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:sk.pkcs8.der",
    key_id = "0xfe584ae7_53790cfd_8601a312_fb32d3c1_b822d112",
    key_type = "Raw",
)

sku_cfg(
    name = "emulation_open",
    sku_name = "emulation_open",
    testonly = True,
    product = "earlgrey_a2",
    si_creator = "nuvoton",
    package = "npcr13",
    target_lc_state = "prod",
    otp = "sv00",
    perso_bins = ["@lowrisc_opentitan//sw/device/silicon_creator/manuf/base/binaries:ft_personalize_sival"],
    owner_fw_boot_str =  "Bare metal PASS!",
    dice_ca = ":fake_dica_ca",
    ext_ca = ":fake_ext_ca",
    token_encrypt_key = "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:rma_unlock_enc_rsa3072.pub.der"
)

sku_cert(
    name = "ot00_dica_ca",
    certificate = "@provisioning_exts//open/keys/ca:dice_ca.pem",
    key = "nuvoton-ot00-ca-ecdsa-0",
    key_id = "0xDBF5003E7CB9EEB524780CCE766E661CFB01C7B2",
    key_type = "Token",
)

sku_cfg(
    name = "ot00",
    sku_name = "ot00",
    testonly = True,
    product = "earlgrey_a2",
    si_creator = "nuvoton",
    package = "npcr13",
    target_lc_state = "prod",
    otp = "ot00",
    perso_bins = ["@provisioning_exts_extra//perso_release:ft_personalize_ot00_fpga_cw340_rom_with_fake_keys.signed.bin"],
    owner_fw_boot_str =  "info: rescue protocol U",
    dice_ca = ":ot00_dica_ca",
    token_encrypt_key = "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:rma_unlock_enc_rsa3072.pub.der"
)
