const model = {
  groups: [
    { id: "all", label: "Everything" },
    { id: "core", label: "Core" },
    { id: "consumer", label: "Consumers" },
    { id: "boundary", label: "Boundaries" },
  ],
  nodes: [
    { id: "source", kind: "boundary", title: "Conversation", subtitle: "Intent and source material", body: "The temporary visual starts with the current explanation, not a permanent publishing workflow.", facts: ["Short-lived by default", "No raw transcript dump"] },
    { id: "builder", kind: "consumer", title: "Producer skill", subtitle: "Creates HTML, CSS, and JS", body: "A specialized skill chooses the right visual form and builds a self-contained artifact.", facts: ["Works without a framework", "Keeps assets local"] },
    { id: "host", kind: "core", title: "Artifact host", subtitle: "Stable lifecycle and URLs", body: "One generic host validates, copies, serves, expires, and revokes artifacts for every producer.", facts: ["Loopback-only service", "Random capability URLs"] },
    { id: "browser", kind: "consumer", title: "Browser", subtitle: "Interactive local view", body: "The browser handles spatial layout, selection, filtering, and progressive detail that a terminal cannot show well.", facts: ["Responsive layout", "Keyboard-accessible controls"] },
    { id: "tailscale", kind: "boundary", title: "Tailscale Serve", subtitle: "Optional tailnet HTTPS", body: "A reviewed adapter maps a named tailnet URL to the loopback host without exposing it to the public internet.", facts: ["Explicit setup", "Existing routes preserved"] },
    { id: "cleanup", kind: "core", title: "TTL and revoke", subtitle: "Transient by design", body: "Artifacts expire automatically and can be removed immediately without touching their original source files.", facts: ["Bounded retention", "Owned copies only"] },
  ],
  edges: [
    ["source", "builder"], ["builder", "host"], ["host", "browser"],
    ["host", "tailscale"], ["tailscale", "browser"], ["host", "cleanup"],
  ],
};

const nodesRoot = document.querySelector("#nodes");
const filtersRoot = document.querySelector("#filters");
const svg = document.querySelector("#connections");
let selected = "host";
let filter = "all";

function renderFilters() {
  filtersRoot.replaceChildren(...model.groups.map((group) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = group.label;
    button.dataset.filter = group.id;
    button.setAttribute("aria-pressed", String(group.id === filter));
    button.addEventListener("click", () => {
      filter = group.id;
      renderFilters();
      updateNodes();
    });
    return button;
  }));
}

function renderNodes() {
  nodesRoot.replaceChildren(...model.nodes.map((node) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "node";
    button.dataset.id = node.id;
    button.dataset.kind = node.kind;
    const title = document.createElement("strong");
    const subtitle = document.createElement("small");
    title.textContent = node.title;
    subtitle.textContent = node.subtitle;
    button.append(title, subtitle);
    button.addEventListener("click", () => selectNode(node.id));
    return button;
  }));
  updateNodes();
}

function updateNodes() {
  document.querySelectorAll(".node").forEach((element) => {
    const visible = filter === "all" || element.dataset.kind === filter;
    element.classList.toggle("dimmed", !visible);
    element.setAttribute("aria-pressed", String(element.dataset.id === selected));
  });
  drawConnections();
}

function selectNode(id) {
  selected = id;
  const node = model.nodes.find((candidate) => candidate.id === id);
  document.querySelector("#detail-title").textContent = node.title;
  document.querySelector("#detail-body").textContent = node.body;
  document.querySelector("#detail-facts").replaceChildren(...node.facts.map((fact) => {
    const item = document.createElement("li");
    item.textContent = fact;
    return item;
  }));
  updateNodes();
}

function center(rect) {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function boundaryPoint(rect, toward, canvasRect) {
  const origin = center(rect);
  const dx = toward.x - origin.x;
  const dy = toward.y - origin.y;
  const scale = 1 / Math.max(
    Math.abs(dx) / (rect.width / 2),
    Math.abs(dy) / (rect.height / 2),
  );
  return {
    x: origin.x + dx * scale - canvasRect.left,
    y: origin.y + dy * scale - canvasRect.top,
  };
}

function drawConnections() {
  const canvasRect = document.querySelector("#canvas").getBoundingClientRect();
  svg.querySelectorAll("line").forEach((line) => line.remove());
  svg.append(...model.edges.map(([from, to]) => {
    const source = document.querySelector(`[data-id="${from}"]`).getBoundingClientRect();
    const target = document.querySelector(`[data-id="${to}"]`).getBoundingClientRect();
    const sourcePoint = boundaryPoint(source, center(target), canvasRect);
    const targetPoint = boundaryPoint(target, center(source), canvasRect);
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", sourcePoint.x);
    line.setAttribute("y1", sourcePoint.y);
    line.setAttribute("x2", targetPoint.x);
    line.setAttribute("y2", targetPoint.y);
    line.setAttribute("marker-end", "url(#arrowhead)");
    line.classList.toggle("active", from === selected || to === selected);
    return line;
  }));
}

renderFilters();
renderNodes();
selectNode(selected);
new ResizeObserver(drawConnections).observe(document.querySelector("#canvas"));
