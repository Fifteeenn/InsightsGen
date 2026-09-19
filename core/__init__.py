"""InsightsGen core: everything that is not UI.

Modules:
  loader    files -> DataFrames (CSV, multi-sheet Excel)
  profiler  cleaning, type inference, schema summaries, join-key detection
  engine    DuckDB wrapper with a read-only SQL guard
  llm       Groq client: question -> SQL, result -> English
  charts    result shape -> Plotly figure
  pipeline  glues the above into ask(question) -> Answer
"""
