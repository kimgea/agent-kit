# gh-api-get

`gh-api-get` is a portable policy wrapper for read-only GitHub REST requests. It
always invokes `gh api` with `--method GET --hostname github.com` and rejects
GraphQL, method overrides, request bodies, typed fields, caching, custom hosts,
verbose output, and unsafe headers.

Use the shell launcher on Linux/macOS, the `.cmd` launcher on Windows, or invoke
`gh_api_get.py` with Python 3. Add the selected launcher directory to `PATH` only
after reviewing it; installing this tool changes user-wide command behavior and
is intentionally not performed by the toolkit skill installer.

Examples:

```text
gh-api-get /repos/OWNER/REPO
gh-api-get /repos/OWNER/REPO/issues --jq '.[].title'
gh-api-get '/repos/OWNER/REPO/contents/file?ref=v1.0.0' --jq .content
```

Raw fields are retained on GET, matching GitHub CLI's supported query behavior.
