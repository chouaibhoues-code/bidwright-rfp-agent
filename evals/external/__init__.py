"""Stage benchmarks on public datasets (Iteration 1, step 19, and Iteration 5).

Each adapter runs one Bidwright stage on a published benchmark that sits in a folder outside
the repository, and writes only its scores to `evals/results/external/`. The benchmark files
it reads are listed with their hashes in `evals/external/BENCHMARKS.sha256`, and an adapter
refuses files that do not match. Third-party data is never committed.
"""
