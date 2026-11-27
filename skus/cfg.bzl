# Copyright lowRISC contributors (OpenTitan project).
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

EXT_EARLGREY_OTP_CFGS = {
    "ot00": "@provisioning_exts//open/otp/ot00:otp_consts",
    "oe00": "@provisioning_exts//open/otp/ot00_emulation:otp_consts",
}

STANDARD_SKUS = {
    # See documentation in standard_sku, a dictionary with the following keys:
    # - sku: SKU configuration, as documented in
    #   https://github.com/lowRISC/opentitan/blob/earlgrey_1.0.0/sw/device/silicon_creator/manuf/extensions/repo/cfg.bzl
    # - emulation_otp: used for the emulation SKU to replace the `otp` field in `sku`.
    # - dice_ca: label of the SKU certificate information, defined using `sku_cert`.
    # - token_encrypt_key: FIXME clarify
    "ot00": {
        "sku": {
            "otp": "ot00",
            "ca_data": "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:ca_data",
            "dice_libs": ["@lowrisc_opentitan//sw/device/silicon_creator/lib/cert:dice", "@lowrisc_opentitan//sw/device/silicon_creator/lib/cert:dice_mldsa_empty"],
            "host_ext_libs": ["@provisioning_exts//open:ft_ext_lib"],
            "device_ext_libs": ["@provisioning_exts//open:personalize_fw_ext"],
            "ownership_libs": ["@provisioning_exts//open/rom_ext:owner"],
            "rom_ext": "@provisioning_exts//open/binaries/rom_ext:rom_ext_dice_x509_prod",
            "owner_fw": None,
            "ecdsa_key": {"@provisioning_exts//open/keys/root:keyset": "ot00-earlgrey-a2-root-ecdsa-prod-0"},
            "spx_key": {"@provisioning_exts//open/keys/root:spxset": "ot00-earlgrey-a2-root-slhdsa-prod-0"},
            "signature_prefix": "@provisioning_exts//open/signatures/perso",
            "scrambling_bin": "@provisioning_exts//open/binaries/perso:ft_flash_scramble_ot00",
            "perso_bin": "@provisioning_exts//open/binaries/perso:ft_personalize_ot00",
            "orchestrator_cfg": "@provisioning_exts//open/orchestrator:ot00_staging",
            "offline": False,
        },
        "emulation_otp": "oe00",
        "dice_ca": "@provisioning_exts//open/orchestrator:ot00_dice_ca",
        "token_encrypt_key": "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/sival:rma_unlock_enc_rsa3072.pub.der",
    },
}

def standard_sku(name, cfg):
    """
    Return a dictionary of three SKUs:
    - <name>:
      The SKU as described in `cfg["sku"]`, see
      https://github.com/lowRISC/opentitan/blob/earlgrey_1.0.0/sw/device/silicon_creator/manuf/extensions/repo/cfg.bzl
      Binaries are signed offline and integrated via a GitHub Release flow (see create_release.md), which they are then sourced from.
      The DICE CA key for endorsing the Unique Device Secret (UDS) is private - known only to the manufacturer - and so this SKU cannot
      be tested in online FPGA flows.

    - <name>_staging:
       It is the exact same as <name>, except that it can be used in online FPGA flows, as it uses OpenTitan's `emulation_dice_ca`,
       using a fake CA key that is checked into upstream OpenTitan for UDS endorsement.
       This allows for the full manufacturing flow to be tested on an FPGA, using the same signed binaries that are sourced from GitHub Releases
       via an offline signing ceremony.

    - <name>_emulation:
       Its intention is to use the same OTP configuration as the real open-market SKU (except for the root keys), instead making use of the fake
       signing keys defined in `opentitan` so that it can be easily used to test signing flows without requiring any offline step.
       This SKU uses `cfg["emulation_otp"]` for the `otp` SKU parameter and `@provisioning_exts//open/orchestrator:emulation_<name>` for
       the orchestrator configuration.
    """
    return {
        name: cfg["sku"],
        "{}_staging".format(name): cfg["sku"] | {
            "ca_data": "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:ca_data",
            "offline": False,
        },
        "{}_emulation".format(name): cfg["sku"] | {
            "otp": cfg["emulation_otp"],
            "ca_data": "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:ca_data",
            "ownership_libs": ["@lowrisc_opentitan//sw/device/silicon_creator/lib/ownership:test_owner"],
            "rom_ext": "@lowrisc_opentitan//sw/device/silicon_creator/rom_ext:rom_ext_dice_x509_slot_virtual",
            "owner_fw": "@lowrisc_opentitan//sw/device/silicon_owner/bare_metal:bare_metal_slot_b",
            "ecdsa_key": {"@lowrisc_opentitan//sw/device/silicon_creator/lib/ownership/keys/fake:ecdsa_keyset": "app_prod_0"},
            "spx_key": {"@lowrisc_opentitan//sw/device/silicon_creator/lib/ownership/keys/fake:slh_dsa_keyset": "app_prod_0"},
            "signature_prefix": None,
            "orchestrator_cfg": "@provisioning_exts//open/orchestrator:{}_emulation".format(name),
            "offline": False,
        },
    }

EXT_EARLGREY_SKUS = {
    ############################################################################
    # Emulation SKUs
    ############################################################################
    # This SKU is for testing purpose only, notably in CI.
    "fake_do_not_use": {
        "otp": "oe00",
        "ca_data": "@lowrisc_opentitan//sw/device/silicon_creator/manuf/keys/fake:ca_data",
        "dice_libs": ["@lowrisc_opentitan//sw/device/silicon_creator/lib/cert:dice", "@lowrisc_opentitan//sw/device/silicon_creator/lib/cert:dice_mldsa_empty"],
        "host_ext_libs": ["@provisioning_exts//open:ft_ext_lib"],
        "device_ext_libs": ["@provisioning_exts//open:personalize_fw_ext"],
        "ownership_libs": ["@lowrisc_opentitan//sw/device/silicon_creator/lib/ownership:test_owner"],
        "rom_ext": "@lowrisc_opentitan//sw/device/silicon_creator/rom_ext:rom_ext_dice_x509_slot_virtual",
        "owner_fw": "@lowrisc_opentitan//sw/device/silicon_owner/bare_metal:bare_metal_slot_b",
        "ecdsa_key": {"@lowrisc_opentitan//sw/device/silicon_creator/lib/ownership/keys/fake:ecdsa_keyset": "app_prod_0"},
        "spx_key": {"@lowrisc_opentitan//sw/device/silicon_creator/lib/ownership/keys/fake:slh_dsa_keyset": "app_prod_0"},
        "signature_prefix": None,
        "orchestrator_cfg": "@provisioning_exts//open/orchestrator:emulation_open",
    },
} | {
    sku_name: config
    for (sku, std_cfg) in STANDARD_SKUS.items()
    for (sku_name, config) in standard_sku(sku, std_cfg).items()
}

EXT_EXEC_ENV_SILICON_ROM_EXT = {
    #    "@provisioning_exts//shared/exec_env:silicon_owner_gb_rom_ext": None,
}
