"""
EDD Eval Runner Interface
 
Usage:
    uv run python run_eval.py --eval_type backend
    uv run python run_eval.py --eval_type backend --config pr_subset.yaml
"""

import argparse
import sys
import logging

# Why: print() disappears in production. logging lets you control
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# Why: a dict is easier to extend than if/elif chains
# To add a new eval type, just add one line here
EVAL_REGISTRY = {
    "backend": "backend.run_backend_eval", 
}

def run_eval(eval_type: str, config: str | None=None) -> bool:
    """
    Dynamically import and run the eval moduler for the given type.
    Returns True on success, False on failure.
    """
    module_path = EVAL_REGISTRY.get(eval_type)
    
    if module_path is None:
        logger.error(
            "Unknown eval_type '%s'. Available: %s",
            eval_type,
            list(EVAL_REGISTRY.keys())
        )
        return False
    
    # Why dynamic import: avoids importing every eval module at startup
    # If you add 10 eval types later, only the requested one loads
    try:
        import importlib
        module = importlib.import_module(module_path)
    except ImportError as e:
        logger.error("Could not import module '%s' : %s", module_path, e)
        return False
    
    
    # Every eval module must expose a `run(config)` function
    if not hasattr(module, "run"):
        logger.error("Module '%s' has no run() function.", module_path)
        return False

    try:
        module.run(config=config)
        return True
    except Exception:
        logger.exception("Eval '%s' failed with an error.", eval_type)
        return False
    
    
def main():
    parser = argparse.ArgumentParser(description="EDD eval runner interface")
    
    parser.add_argument(
        "--eval_type", 
        type=str, 
        required=True,
        choices=EVAL_REGISTRY.keys(),
        help="Which eval suite to run.",
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Optional config filename (e.g. pr_subset.yaml).",
    )
        
    args = parser.parse_args()
    
    success = run_eval(args.eval_type, config=args.config)
    
    # Why sys.exit: in CI (GitHub Actions), a non-zero exit code
    if not success:
        sys.exit(1)

# Why this guard: without it, `main()` runs on import too.
if __name__ == "__main__":
    main()