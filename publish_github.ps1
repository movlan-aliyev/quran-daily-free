# One-time: set local git identity, commit if needed, create GitHub repo (gh), push.
# Requires: Git; for auto-create, install GitHub CLI and run: gh auth login
# Otherwise create an EMPTY repo at https://github.com/new named quran-daily-free, then re-run.

Set-Location $PSScriptRoot

$repo = "quran-daily-free"
$owner = "robert-movlan"

git config user.email "robert.movlan@outlook.com"
git config user.name "Robert Movlan"

git rev-parse HEAD *>$null
if ($LASTEXITCODE -ne 0) {
    git add -A
    git status
    git commit -m "Initial commit: daily Quran email and GitHub Actions"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$hasOrigin = $false
git remote get-url origin *>$null
if ($LASTEXITCODE -eq 0) { $hasOrigin = $true }

if (-not $hasOrigin) {
    git remote add origin "https://github.com/$owner/$repo.git"
}

# Try push first (repo may already exist)
git push -u origin main 2>&1 | Out-Host
if ($LASTEXITCODE -eq 0) {
    Write-Host "Done: pushed to https://github.com/$owner/$repo"
    exit 0
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($gh) {
    Write-Host "Push failed; trying: gh repo create $owner/$repo --public --source=. --remote=origin --push"
    gh repo create "$owner/$repo" --public --source=. --remote=origin --push
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Done."
        exit 0
    }
}

Write-Host @"

Push failed. Do this manually:
  1. Open https://github.com/new
  2. Repository name: $repo
  3. Do NOT add README, .gitignore, or license (keep empty).
  4. Create repository, then run:

     cd "$PSScriptRoot"
     git push -u origin main

"@

exit 1
