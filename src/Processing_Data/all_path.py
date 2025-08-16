from operator import index
import os
def path_Documents_folder():
    current_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(current_dir, ".."))
    project_root1 = os.path.abspath(os.path.join(project_root, ".."))
    documents_folder = os.path.join(project_root1, "Documents")
    output_folder = os.path.abspath(os.path.join(os.path.dirname(__file__),"..", "Data"))

    return documents_folder, output_folder
