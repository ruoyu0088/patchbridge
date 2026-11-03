# PatchBridge profile v1
# This example points at the bundled demo project.  If you move the
# repository, update `root` to its new absolute path.
name: PatchBridge Demo
root: C:\Users\ruoyu\workspace\patchbridge\examples\demo-project
mode: exclude

[rules]
.git/
__pycache__/
*.pyc
.pytest_cache/
# Re-include a file that would otherwise be excluded.
!README.md
