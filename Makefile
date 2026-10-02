.PHONY: test test-v2 test-v3 demo demo-v2 demo-v3 api

test:
	PYTHONPATH=src python3 -m pytest -q

test-v2:
	PYTHONPATH=src python3 -m unittest discover -s tests_v2 -v

test-v3:
	PYTHONPATH=src python3 -m pytest -q tests_v3

demo:
	PYTHONPATH=src python3 run_demo.py

demo-v2:
	PYTHONPATH=src python3 run_v2.py

demo-v3:
	PYTHONPATH=src python3 run_v3.py

api:
	PYTHONPATH=src uvicorn fieldshift.api.app:app --host 0.0.0.0 --port 8000 --reload
