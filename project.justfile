## Add your own just recipes here. This is imported by the main justfile.

# ============== Notebook recipes ==============

# Execute notebooks with papermill and copy to docs for mkdocs-jupyter to render
[group('documentation')]
render-notebooks:
  @echo "Executing notebooks and copying to docs..."
  @mkdir -p notebooks/output docs/notebooks
  # Execute with papermill (suppress warnings for cleaner output)
  PYTHONWARNINGS="ignore::DeprecationWarning,ignore::UserWarning" uv run papermill notebooks/01_getting_started.ipynb notebooks/output/01_getting_started.ipynb
  PYTHONWARNINGS="ignore::DeprecationWarning,ignore::UserWarning" uv run papermill notebooks/02_advanced_usage.ipynb notebooks/output/02_advanced_usage.ipynb
  PYTHONWARNINGS="ignore::DeprecationWarning,ignore::UserWarning" uv run papermill notebooks/03_python_api.ipynb notebooks/output/03_python_api.ipynb
  # Copy executed notebooks to docs for mkdocs-jupyter plugin to render
  cp notebooks/output/01_getting_started.ipynb docs/notebooks/01_getting_started.ipynb
  cp notebooks/output/02_advanced_usage.ipynb docs/notebooks/02_advanced_usage.ipynb
  cp notebooks/output/03_python_api.ipynb docs/notebooks/03_python_api.ipynb
  @echo "✅ Notebooks executed and copied to docs/notebooks/"

# Run all Jupyter notebooks using papermill to test they execute without errors
[group('documentation')]
run-notebooks:
  @echo "Running notebooks with papermill..."
  @mkdir -p notebooks/output
  uv run papermill notebooks/01_getting_started.ipynb notebooks/output/01_getting_started_output.ipynb
  uv run papermill notebooks/02_advanced_usage.ipynb notebooks/output/02_advanced_usage_output.ipynb
  uv run papermill notebooks/03_python_api.ipynb notebooks/output/03_python_api_output.ipynb
  @echo "✅ All notebooks executed successfully!"

# Run a specific notebook
[group('documentation')]
run-notebook NOTEBOOK:
  @echo "Running notebook: {{NOTEBOOK}}"
  @mkdir -p notebooks/output
  uv run papermill notebooks/{{NOTEBOOK}} notebooks/output/{{NOTEBOOK}}

# Clean notebook outputs
[group('documentation')]
clean-notebooks:
  @echo "Cleaning notebook outputs..."
  rm -rf notebooks/output docs/notebooks
  @echo "✅ Notebook outputs cleaned"

# Start Jupyter Lab for interactive notebook development
[group('documentation')]
jupyter:
  uv run jupyter lab notebooks/
