# Full-caller detail parity prerequisite (CLAUDE-APP-0431, replaces 0370 in full)

This additive engineering check extends coverage to P1 `snapshot.comparison`
and every P2 probe's `bounds`. It does not change any runtime predictor or
connect a UI/report consumer. The previously accepted summary-only entrypoint
is retained unchanged and is not part of this new first execution.

The new Python exporter writes **full raw snapshots**, including every nested
candidate, bound, scenario, nominal/conservative/optimistic row, replayed
estimate, leg, projection, status, provenance, safety flag and null. The JS
comparator checks exact key sets, list order, strings/booleans/nulls, and finite
numbers with relative tolerance `1e-8 * max(1, abs(a), abs(b))`. No detail field
is deleted. Output leaves `exit_air_heading_deg` and `exit_ground_heading_deg`
use one explicit exception: exactly 360 is compared as 0. Both sides must be
finite and within [0,360]. No general modulo, circular tolerance or wider
numeric tolerance is used. Other fields and all inputs retain the old comparison.
Original Python vectors and runtime values remain unmodified. Inputs and case identities are also checked against the declared
new fixtures rather than trusting an arbitrary vector file.

The only textual normalization is a nonempty string `reason` on a row whose
`status` is `unsupported`, within P1 comparison, P2 bounds or P2 scenario
subtrees. These backend exception/prose leaves become `<backend diagnostic>`
on both sides; the key, type, presence and unsupported status remain checked.
Raw Python diagnostic text remains in the exported evidence. Stable reasons
elsewhere (including the P2 probe's aggregate `reason`) are compared exactly.
This is not byte-for-byte diagnostic prose parity.

Eight new streams, four ticks each (32 total): safe detail, risky current with
alternative ranking, nonzero uncertainty with two candidates/two prefix-ordered
probes, unsupported P1, unsupported P2, hybrid in explicit FW mode, mission
version reset, and unsupported recovery endpoint with supported energy bounds.
The nine original JS control groups include nested numeric/field-deletion mutations to
prove the new detail trees are compared. All fixtures are synthetic; no model,
device, flight, sensor or mission feasibility is validated.

## Replacement isolated execution (Claude)

0370 run1 failed at safe_detail[0] exit_ground_heading_deg (JS0/Python360).
Keep that failure and its raw vector unchanged. The Python exporter is byte-for-
byte unchanged from 0370. Reuse that vector after checking its full SHA256;
do not repeat the successful exporter or the nine passed local control groups.
The replacement default comparison runs five NEW angle groups and all 32 ticks.
The commands below document exporter creation only if its original evidence is
unavailable, not an instruction to rerun an already successful export.


Start from a clean `dc069b5ff5c790bfd33d8b2b783013f22a52ef83` checkout. Verify
the delivery manifest, native `git apply --check --whitespace=error` then apply
the patch once, and compare all three new files with their LF hashes. The 121
existing files must remain unchanged (raw/LF reference labels are explicit).

From the checkout root, with a **new** evidence directory outside the source:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import ast,pathlib; ast.parse(pathlib.Path("gcs_demo/full_orchestration_detail_vectors.py").read_text(encoding="utf-8"))'
PYTHONDONTWRITEBYTECODE=1 python3 -m gcs_demo.full_orchestration_detail_vectors <new-evidence>/detail_vectors.json
node gcs_demo/qml/test/test_typed_full_detail_parity.js <new-evidence>/detail_vectors.json
```

Keep each first stdout/stderr/exit and hash the Python vector file. Expected:
contract `typed_full_orchestration_detail_P1_comparison_P2_bounds_v1`, eight
cases, 32 ticks, five NEW angle groups, zero omitted detail fields. Do not run the old
14-group entrypoint, old Python 12 controls, existing smoke, or research suites
just to repeat their successful evidence. Preserve the first failure and send
its original output if any step fails. The exporter refuses an existing output
path; do not overwrite earlier vectors or logs.

No runtime calculation changed: old wind-route, energy, summary parity and
Python tests have no new runtime impact and must not be rerun for this patch.
Only this failed detailed comparison and five new angle controls need first
execution. Unsupported-reason normalization is unchanged and still provisional
until the full comparison passes without hiding another difference.

UI/report reading of these fields remains blocked until this **real Python to
JS** comparison passes and its source/evidence hashes are recorded. Local JS
controls alone do not fulfill the cross-language prerequisite. Candidates and
geometry implementation, endpoint/landing, typed UI/report, T6/T7 remain later
batches. `human_approved`/`training_release` are unaffected.
