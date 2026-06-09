PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: binary quickrun test clean

binary:
	$(PYTHON) -m PyInstaller --clean --noconfirm chartpatch.spec

quickrun: binary
	./dist/chartpatch quickrun chartpatch.yaml

test:
	$(PYTHON) -m pytest -q

clean:
	rm -rf build dist
