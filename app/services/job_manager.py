# Original Structure Snippet (Conceptual, showing placement of fix)
# ... inside function submit_analysis_job(source_file: str):
# job = JobMetadata(...)
# # Source path is only set later on success
# try:
#     result = clipper.analyze(source_file, ...)
#     job.set_success_details(...) # <-- source_path assigned here
# except Exception as e:
#     job.handle_failure(...)

# --- Implementation of Fix (Assuming 'source_file' is the path to the uploaded resource) ---

def submit_analysis_job(source_file_path: str, job_params: dict):
    """
    Submits a new analysis job and ensures metadata linkage before processing begins.
    """
    # 1. Instantiate or retrieve the job record object
    job = JobMetadata()

    # FIX: Set source_path immediately upon submission/ingestion
    # This link must exist regardless of runtime success or failure.
    try:
        if os.path.isdir(source_file_path):
             raise ValueError("Input path is a directory, expected file.")
        job.set_source_path(os.path.abspath(source_file_path))

        # 2. Perform analysis (Original flow continues here)
        clipper = AnalysisService('app/services/clipper.py')
        success = clipper.analyze(source_file_path, job_params)

        if success:
            job.mark_complete()
        else:
            # Job failed during execution. But now source_path is set.
            job.record_failure(exception=...)
            
    except Exception as e:
        # Handles submission/setup failures gracefully, but job has a path anyway.
        print(f"Job submission or initial processing failed: {e}")
        pass
