# Framework output

Read this reference only when a framework build needs relative assets, SPA
fallback, or a final base path before publication.

The host serves each artifact below:

```text
/agent-artifacts/c/<artifact-id>/
```

For Vite, prefer a relative build base:

```js
export default { base: "./" }
```

Publish the resulting `dist/` directory. Client-side routers also need `--spa`
when their routes are not emitted as files.

Frameworks that require an absolute base path need an ID before building:

```bash
python <skill-dir>/scripts/artifact_host.py reserve --title "Preview" --ttl 4h --json
```

Use the slash-free `content_base_path` from the JSON as the build-time base, then
publish with the reserved `id`. For a Next.js static export, use that path as
`basePath` and configure a directory-index export shape:

```js
export default {
  output: "export",
  basePath: process.env.ARTIFACT_BASE_PATH,
  trailingSlash: true,
}
```

Set `ARTIFACT_BASE_PATH` to the reserved `content_base_path` before the producer
builds, then publish its export directory. Next.js rejects a non-empty `basePath`
ending in `/`; `trailingSlash: true` emits secondary routes as directory index
files that this static host can serve without rewrite rules. This is a build-output
contract, not permission for the host to run Node or a package manager.

For an already-running dynamic app, reserve the ID, configure the app for the same
base path, and proxy it with `--id <id> --preserve-prefix`. Ordinary GET/HEAD HTTP
works; WebSockets, server lifecycle, authentication, databases, and production
reliability remain outside this host.
