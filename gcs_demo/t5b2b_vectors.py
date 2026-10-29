"""NEW parity emitter; never imports/runs older research scripts."""
import json
from .test_airframe_t5b2b import vector_rows

if __name__ == "__main__":
    print(json.dumps(vector_rows(), allow_nan=False))
