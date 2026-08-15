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

Use `content_base_path` from the JSON as the build-time base, then publish with
the reserved `id`. For a Next.js static export, set `output: "export"` and use
that path as `basePath` before building; publish its export directory. This is a
build-output contract, not permission for the host to run Node or a package manager.

For an already-running dynamic app, reserve the ID, configure the app for the same
base path, and proxy it with `--id <id> --preserve-prefix`. Ordinary GET/HEAD HTTP
works; WebSockets, server lifecycle, authentication, databases, and production
reliability remain outside this host.
