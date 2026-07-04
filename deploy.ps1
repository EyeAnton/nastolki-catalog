$token = Get-Content "$env:USERPROFILE\.nastolki-token" -Raw -ErrorAction Stop
$env:CLOUDFLARE_API_TOKEN = $token.Trim()
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory dist | Out-Null
Copy-Item index.html dist\
Copy-Item -Recurse covers dist\
wrangler pages deploy dist\ --project-name nastolki-catalog --branch main --commit-dirty=true
