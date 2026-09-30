"""Phase 1 data must stay byte-identical whatever the generator learns later."""

import hashlib
import json

import pytest

from experiment.generate import generate

# sha256 of the JSON dump of every generated table for seed 7, computed before the generator gained
# profiles and variants. The phase 1 traces and truth files depend on these exact bytes.
V1_HASHES = {
    5: "214dad7f93ce82684191e41b90bffb78ea5107db021a1cccba6c28fdb529a957",
    10: "e4638a6fe10c07a6d19cba688d08b9fa38f19ae3e40ab07f2f348ac599a1138b",
    20: "b395869f127fcb54de68d428e9f7580c3e89d3f9d399b7317cf52a08ba8c8686",
    40: "5ac90e85fb0060a2bed26e5b4aac9bc7fb20987cfbb863ee329d6b1315076f83",
    60: "7429645bd3c1725af52ca07c1f93e6254fdca18e62b8d9281e9448295e6e0b9c",
    80: "62294d240b31099dbbfd261d00f2e9e56cd961e1a31ef4d356c16e3933845cf0",
    100: "3975f4ce1feff66b741eda3cf90630ec9ddc518bb0966e14e90c1750603c1457",
    120: "fc652c476bf568f13e2d86dbb08ea70ecca0053de6e37378dbdbc556481d9ca9"
}


def digest(ds) -> str:
    dump = json.dumps(
        [ds.matters, ds.dockets, ds.emails, ds.time_entries, ds.scenarios, ds.email_owner, ds.attorneys],
        sort_keys=True, default=str,
    )
    return hashlib.sha256(dump.encode()).hexdigest()


@pytest.mark.parametrize("n", sorted(V1_HASHES))
def test_v1_base_is_byte_identical_to_phase_1(n):
    assert digest(generate(n, 7)) == V1_HASHES[n]
    assert digest(generate(n, 7, profile="v1", variant="base")) == V1_HASHES[n]
