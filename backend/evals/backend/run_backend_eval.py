"""
Backend Eval Runner
 
Reads a dataset, runs evaluation, writes results.
 
Usage (called by run_eval.py, not directly):
    Internally called via:  module.run(config="pr_subset.yaml")
    
Now it just a test version
"""

import json
from pathlib import Path

script_location = Path(__file__).resolve().parent

def secure_eval_json_file(input_filename: str ="smoke.json",
                          output_filename: str ="result.json"):
    try:
        with open(f"{script_location}/datasets/{input_filename}", "r", encoding="utf-8") as file:
            data = json.load(file)

        # process here 
        # eval_funciton(input_file, ....)
        
        result = {
            "status": "success",
            "input_file": input_filename,
            "data": data
        }
        
        with open(f"{script_location}/results/{output_filename}", "w", encoding="utf-8") as file:
            json.dump(result, file, indent=4, ensure_ascii=False)
        
        return result
        
    except FileNotFoundError:
        print(f"Error: file '{input_filename} not found.")
        return None
    
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in '{input_filename}'.")
        print(f"Details: {e}")
        return None
    
# A contract with the run_eval
def run(config: str | None = None):
    secure_eval_json_file()