/**
 * CyberWatch Topology Visualization
 * Interactive ASN network topology with force-directed layout
 */

// Global state
const state = {
  nodes: [],
  edges: [],
  maxTraffic: 0,
  transform: { x: 0, y: 0, scale: 1 },
  selectedNode: null,
  viewMode: 'top', // 'top' or 'explore'
  isDragging: false,
  dragStart: { x: 0, y: 0 },
};

// Force simulation parameters
const physics = {
  repulsion: 20000,       // Strong repulsion to prevent overlap
  attraction: 0.006,      // Weaker attraction for more spacing
  damping: 0.80,          // More damping for stability
  centerPull: 0.003,      // Slight center pull to keep graph together
  minDistance: 340,       // Cards are ~200px wide, need more space
  maxVelocity: 8,         // Slower movement for stability
  cardWidth: 200,         // Card dimensions for collision
  cardHeight: 150,
};

// DOM elements
let nodesContainer, svgElement, edgesGroup, detailPanel, loadingOverlay;
let statusBanner, statAsnCount, statEdgeCount, statTotalTraffic;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  initializeElements();
  attachEventListeners();
  loadTopology();
});

function initializeElements() {
  nodesContainer = document.getElementById('nodes-container');
  svgElement = document.getElementById('topology-svg');
  edgesGroup = document.getElementById('edges-group');
  detailPanel = document.getElementById('detail-panel');
  loadingOverlay = document.getElementById('loading-overlay');
  statusBanner = document.getElementById('graph-status');
  statAsnCount = document.getElementById('stat-asn-count');
  statEdgeCount = document.getElementById('stat-edge-count');
  statTotalTraffic = document.getElementById('stat-total-traffic');
}

function attachEventListeners() {
  // View mode toggle
  document.getElementById('btn-top-asns').addEventListener('click', () => {
    setViewMode('top');
  });
  
  document.getElementById('btn-explore-asn').addEventListener('click', () => {
    setViewMode('explore');
  });
  
  // Explore form
  document.getElementById('explore-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const asn = parseInt(document.getElementById('explore-asn').value);
    const depth = parseInt(document.getElementById('depth').value);
    if (asn) {
      loadTopology({ asn, depth });
    }
  });
  
  // Filters
  document.getElementById('btn-apply-filters').addEventListener('click', () => {
    loadTopology();
  });
  
  document.getElementById('btn-reset-view').addEventListener('click', () => {
    resetView();
  });
  
  // Zoom controls
  document.getElementById('btn-zoom-in').addEventListener('click', () => {
    zoom(1.3);
  });
  
  document.getElementById('btn-zoom-out').addEventListener('click', () => {
    zoom(0.7);
  });
  
  document.getElementById('btn-zoom-reset').addEventListener('click', () => {
    resetTransform();
  });
  
  // Detail panel close
  document.getElementById('btn-close-detail').addEventListener('click', () => {
    closeDetailPanel();
  });
  
  // Canvas panning
  const canvas = document.getElementById('topology-canvas');
  canvas.addEventListener('mousedown', startPan);
  canvas.addEventListener('mousemove', doPan);
  canvas.addEventListener('mouseup', endPan);
  canvas.addEventListener('mouseleave', endPan);
  
  // Zoom with mouse wheel
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    zoom(delta);
  });
}

function setViewMode(mode) {
  state.viewMode = mode;
  
  const topBtn = document.getElementById('btn-top-asns');
  const exploreBtn = document.getElementById('btn-explore-asn');
  const exploreForm = document.getElementById('explore-form');
  
  if (mode === 'top') {
    topBtn.classList.add('active');
    exploreBtn.classList.remove('active');
    exploreForm.style.display = 'none';
    loadTopology();
  } else {
    topBtn.classList.remove('active');
    exploreBtn.classList.add('active');
    exploreForm.style.display = 'block';
  }
}

async function loadTopology(params = {}) {
  showLoading(true);
  showMessage(statusBanner, 'Loading topology...', 'info');
  
  try {
    let url = '/graph/topology?';
    const queryParams = new URLSearchParams();
    
    if (params.asn) {
      queryParams.append('asn', params.asn);
      queryParams.append('depth', params.depth || 1);
    } else if (state.viewMode === 'top') {
      const sortBy = document.getElementById('sort-by').value;
      const limit = document.getElementById('limit').value;
      const country = document.getElementById('country-filter').value.trim();
      
      queryParams.append('sort_by', sortBy);
      queryParams.append('limit', limit);
      if (country) {
        queryParams.append('country', country.toUpperCase());
      }
    }
    
    url += queryParams.toString();
    console.log('Fetching topology from:', url);
    const data = await fetchJson(url);
    console.log('Topology response:', data);
    
    if (data.nodes && data.nodes.length > 0) {
      console.log('Rendering', data.nodes.length, 'nodes and', (data.edges || []).length, 'edges');
      state.nodes = data.nodes.map(node => ({
        ...node,
        x: Math.random() * 800 + 200,
        y: Math.random() * 600 + 150,
        vx: 0,
        vy: 0,
      }));
      
      state.edges = data.edges || [];
      state.maxTraffic = Math.max(...state.nodes.map(n => n.measurement_count || 0), 1);
      
      renderTopology();
      startSimulation();
      updateStats();
      showMessage(statusBanner, `Loaded ${state.nodes.length} ASNs`, 'success');
    } else {
      console.warn('No ASN data returned:', data);
      const message = data.message || 'No ASN data available. Run traceroutes and click "Enrich Data" in Settings.';
      showMessage(statusBanner, message, 'error');
      clearTopology();
    }
  } catch (err) {
    console.error('Failed to load topology:', err);
    showMessage(statusBanner, err.message || 'Failed to load topology', 'error');
    clearTopology();
  } finally {
    showLoading(false);
  }
}

function renderTopology() {
  // Clear existing
  nodesContainer.innerHTML = '';
  edgesGroup.innerHTML = '';
  
  // Render edges
  state.edges.forEach(edge => {
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.classList.add('cw-edge');
    line.setAttribute('data-source', edge.source);
    line.setAttribute('data-target', edge.target);
    
    // Vary stroke width based on observed count
    const strokeWidth = Math.max(1, Math.min(5, (edge.observed_count || 1) / 10));
    line.setAttribute('stroke-width', strokeWidth);
    
    edgesGroup.appendChild(line);
  });
  
  // Render nodes
  state.nodes.forEach(node => {
    const card = createASNCard(node);
    nodesContainer.appendChild(card);
  });
  
  updatePositions();
}

function createASNCard(node) {
  const card = document.createElement('div');
  card.classList.add('cw-asn-card');
  card.setAttribute('data-asn', node.asn);
  
  // Traffic intensity for visual feedback
  const trafficRatio = (node.measurement_count || 0) / state.maxTraffic;
  const intensity = Math.max(0.3, trafficRatio);
  
  // Get neighbors for this node
  const neighbors = getNodeNeighbors(node.asn);
  const neighborCount = neighbors.length;
  
  card.innerHTML = `
    <div class="cw-asn-card-header">
      <span class="cw-asn-number">AS${node.asn}</span>
      ${node.country ? `<span class="cw-country-badge">${node.country}</span>` : ''}
    </div>
    <div class="cw-asn-org">${node.org_name || `AS${node.asn}`}</div>
    <div class="cw-card-metrics">
      <div class="cw-metric-row">
        <span class="cw-metric-label">Traffic:</span>
        <span class="cw-metric-value">${formatNumber(node.measurement_count || 0)}</span>
      </div>
      ${node.avg_rtt ? `
      <div class="cw-metric-row">
        <span class="cw-metric-label">Avg RTT:</span>
        <span class="cw-metric-value">${node.avg_rtt.toFixed(1)}ms</span>
      </div>
      ` : ''}
      <div class="cw-metric-row">
        <span class="cw-metric-label">Neighbors:</span>
        <span class="cw-metric-value">${neighborCount}</span>
      </div>
    </div>
    <div class="cw-traffic-bar">
      <div class="cw-traffic-fill" style="width: ${trafficRatio * 100}%; opacity: ${intensity}"></div>
    </div>
    ${neighborCount > 0 ? `
    <div class="cw-neighbor-indicators" data-asn="${node.asn}">
      ${neighbors.slice(0, 6).map((n, i) => `
        <div class="cw-neighbor-dot" data-neighbor="${n}" title="AS${n}" style="--dot-index: ${i}"></div>
      `).join('')}
      ${neighborCount > 6 ? `<span class="cw-neighbor-more">+${neighborCount - 6}</span>` : ''}
    </div>
    ` : ''}
  `;
  
  // Click handler
  card.addEventListener('click', (e) => {
    e.stopPropagation();
    selectNode(node);
  });
  
  return card;
}

// Helper to get neighbors for a specific ASN
function getNodeNeighbors(asn) {
  const neighbors = [];
  state.edges.forEach(edge => {
    if (edge.source === asn && !neighbors.includes(edge.target)) {
      neighbors.push(edge.target);
    } else if (edge.target === asn && !neighbors.includes(edge.source)) {
      neighbors.push(edge.source);
    }
  });
  return neighbors;
}

function selectNode(node) {
  // Update selected state
  if (state.selectedNode) {
    const prevCard = document.querySelector(`[data-asn="${state.selectedNode.asn}"]`);
    if (prevCard) prevCard.classList.remove('active');
  }
  
  state.selectedNode = node;
  const card = document.querySelector(`[data-asn="${node.asn}"]`);
  if (card) card.classList.add('active');
  
  // Highlight connected edges
  document.querySelectorAll('.cw-edge').forEach(edge => {
    const source = parseInt(edge.getAttribute('data-source'));
    const target = parseInt(edge.getAttribute('data-target'));
    
    if (source === node.asn || target === node.asn) {
      edge.classList.add('highlight');
    } else {
      edge.classList.remove('highlight');
    }
  });
  
  // Show detail panel
  showDetailPanel(node);
}

async function showDetailPanel(node) {
  detailPanel.classList.add('open');
  document.getElementById('detail-title').textContent = `AS${node.asn}`;
  
  const content = document.getElementById('detail-content');
  content.innerHTML = '<div class="cw-loader" style="margin: 2rem auto;"></div>';
  
  try {
    // Fetch full ASN details
    const data = await fetchJson(`/asn/${node.asn}`);
    
    const neighbors = data.neighbors || [];
    const prefixes = data.prefixes || [];
    
    content.innerHTML = `
      <div class="cw-detail-section">
        <h4>Organization</h4>
        <div class="cw-detail-item">
          <div class="cw-detail-value">${node.org_name || `AS${node.asn}`}</div>
        </div>
      </div>
      
      <div class="cw-detail-section">
        <h4>Statistics</h4>
        <div class="cw-detail-grid">
          <div class="cw-detail-item">
            <div class="cw-detail-label">Country</div>
            <div class="cw-detail-value">${node.country || '—'}</div>
          </div>
          <div class="cw-detail-item">
            <div class="cw-detail-label">Neighbors</div>
            <div class="cw-detail-value">${neighbors.length}</div>
          </div>
          <div class="cw-detail-item">
            <div class="cw-detail-label">Measurements</div>
            <div class="cw-detail-value">${formatNumber(node.measurement_count || 0)}</div>
          </div>
          ${node.avg_rtt ? `
          <div class="cw-detail-item">
            <div class="cw-detail-label">Avg RTT</div>
            <div class="cw-detail-value">${node.avg_rtt.toFixed(1)}ms</div>
          </div>
          ` : ''}
          ${node.dns_query_count ? `
          <div class="cw-detail-item">
            <div class="cw-detail-label">DNS Queries</div>
            <div class="cw-detail-value">${formatNumber(node.dns_query_count)}</div>
          </div>
          ` : ''}
          <div class="cw-detail-item">
            <div class="cw-detail-label">Prefixes</div>
            <div class="cw-detail-value">${prefixes.length}</div>
          </div>
        </div>
      </div>
      
      ${neighbors.length > 0 ? `
      <div class="cw-detail-section">
        <h4>Connected ASNs</h4>
        <div class="cw-neighbor-chips">
          ${neighbors.slice(0, 20).map(n => 
            `<span class="cw-chip cw-chip-link" data-neighbor-asn="${n}">AS${n}</span>`
          ).join('')}
          ${neighbors.length > 20 ? `<span class="cw-chip">+${neighbors.length - 20} more</span>` : ''}
        </div>
      </div>
      ` : ''}
      
      ${prefixes.length > 0 ? `
      <div class="cw-detail-section">
        <h4>IP Prefixes</h4>
        <div class="cw-prefix-list">
          ${prefixes.slice(0, 10).map(p => 
            `<span class="cw-chip">${p}</span>`
          ).join('')}
          ${prefixes.length > 10 ? `<span class="cw-chip">+${prefixes.length - 10} more</span>` : ''}
        </div>
      </div>
      ` : ''}
      
      <div class="cw-detail-section">
        <h4>External Resources</h4>
        <div class="cw-external-links">
          <a href="https://bgp.he.net/AS${node.asn}" target="_blank" class="cw-external-link">
            <span>Hurricane Electric BGP Toolkit</span>
            <span>↗</span>
          </a>
          <a href="https://www.peeringdb.com/asn/${node.asn}" target="_blank" class="cw-external-link">
            <span>PeeringDB</span>
            <span>↗</span>
          </a>
          <a href="/asn/${node.asn}" class="cw-external-link">
            <span>ASN Explorer (CyberWatch)</span>
            <span>→</span>
          </a>
        </div>
      </div>
      
      <div class="cw-detail-section">
        <h4>Actions</h4>
        <button class="cw-btn-primary" onclick="exploreFromASN(${node.asn})">
          Explore from this ASN
        </button>
      </div>
    `;
    
    // Attach neighbor chip click handlers
    content.querySelectorAll('[data-neighbor-asn]').forEach(chip => {
      chip.addEventListener('click', () => {
        const neighborAsn = parseInt(chip.getAttribute('data-neighbor-asn'));
        const neighborNode = state.nodes.find(n => n.asn === neighborAsn);
        if (neighborNode) {
          selectNode(neighborNode);
        } else {
          // ASN not currently in view, load it
          exploreFromASN(neighborAsn);
        }
      });
    });
    
  } catch (err) {
    console.error('Failed to load ASN details:', err);
    content.innerHTML = `<p class="cw-muted">Failed to load details: ${err.message}</p>`;
  }
}

function closeDetailPanel() {
  detailPanel.classList.remove('open');
  
  if (state.selectedNode) {
    const card = document.querySelector(`[data-asn="${state.selectedNode.asn}"]`);
    if (card) card.classList.remove('active');
    state.selectedNode = null;
  }
  
  // Remove edge highlights
  document.querySelectorAll('.cw-edge').forEach(edge => {
    edge.classList.remove('highlight');
  });
}

function exploreFromASN(asn) {
  state.viewMode = 'explore';
  document.getElementById('btn-explore-asn').classList.add('active');
  document.getElementById('btn-top-asns').classList.remove('active');
  document.getElementById('explore-form').style.display = 'block';
  document.getElementById('explore-asn').value = asn;
  
  closeDetailPanel();
  loadTopology({ asn, depth: 1 });
}

// Make it globally available for inline onclick
window.exploreFromASN = exploreFromASN;

// Force-directed layout simulation
let simulationInterval = null;

function startSimulation() {
  if (simulationInterval) {
    clearInterval(simulationInterval);
  }
  
  let iterations = 0;
  const maxIterations = 300;
  
  simulationInterval = setInterval(() => {
    applyForces();
    updatePositions();
    
    iterations++;
    if (iterations >= maxIterations) {
      clearInterval(simulationInterval);
      simulationInterval = null;
    }
  }, 16); // ~60fps
}

function applyForces() {
  const nodes = state.nodes;
  const centerX = (window.innerWidth - 320) / 2;
  const centerY = window.innerHeight / 2;
  
  // Reset forces
  nodes.forEach(node => {
    node.fx = 0;
    node.fy = 0;
  });
  
  // Repulsion between all nodes with box collision awareness
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x;
      const dy = nodes[j].y - nodes[i].y;
      const distSq = dx * dx + dy * dy;
      const dist = Math.sqrt(distSq) || 1;
      
      // Calculate overlap based on card dimensions
      const overlapX = physics.cardWidth - Math.abs(dx);
      const overlapY = physics.cardHeight - Math.abs(dy);
      const isOverlapping = overlapX > 0 && overlapY > 0;
      
      if (dist < physics.minDistance || isOverlapping) {
        // Stronger force when overlapping
        const multiplier = isOverlapping ? 3 : 1;
        const force = (physics.repulsion * multiplier) / (distSq + 100);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        
        nodes[i].fx -= fx;
        nodes[i].fy -= fy;
        nodes[j].fx += fx;
        nodes[j].fy += fy;
      }
    }
  }
  
  // Attraction along edges
  state.edges.forEach(edge => {
    const source = nodes.find(n => n.asn === edge.source);
    const target = nodes.find(n => n.asn === edge.target);
    
    if (source && target) {
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      
      // Only attract if beyond minimum distance
      if (dist > physics.minDistance * 0.8) {
        const force = (dist - physics.minDistance * 0.7) * physics.attraction;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        
        source.fx += fx;
        source.fy += fy;
        target.fx -= fx;
        target.fy -= fy;
      }
    }
  });
  
  // Center pull
  nodes.forEach(node => {
    const dx = centerX - node.x;
    const dy = centerY - node.y;
    node.fx += dx * physics.centerPull;
    node.fy += dy * physics.centerPull;
  });
  
  // Apply forces to velocity
  nodes.forEach(node => {
    node.vx = (node.vx + node.fx) * physics.damping;
    node.vy = (node.vy + node.fy) * physics.damping;
    
    // Clamp velocity
    const speed = Math.sqrt(node.vx * node.vx + node.vy * node.vy);
    if (speed > physics.maxVelocity) {
      node.vx = (node.vx / speed) * physics.maxVelocity;
      node.vy = (node.vy / speed) * physics.maxVelocity;
    }
    
    // Update position
    node.x += node.vx;
    node.y += node.vy;
  });
}

function updatePositions() {
  // Update node positions
  state.nodes.forEach(node => {
    const card = document.querySelector(`[data-asn="${node.asn}"]`);
    if (card) {
      card.style.left = `${node.x}px`;
      card.style.top = `${node.y}px`;
      
      // Apply level of detail based on zoom
      if (state.transform.scale < 0.6) {
        card.classList.add('low-detail');
      } else {
        card.classList.remove('low-detail');
      }
    }
  });
  
  // Update edge positions
  state.edges.forEach(edge => {
    const source = state.nodes.find(n => n.asn === edge.source);
    const target = state.nodes.find(n => n.asn === edge.target);
    
    if (source && target) {
      const line = document.querySelector(
        `line[data-source="${edge.source}"][data-target="${edge.target}"]`
      );
      
      if (line) {
        // Offset to card center (100px = half card width, 75px ≈ half height)
        line.setAttribute('x1', source.x + 100);
        line.setAttribute('y1', source.y + 75);
        line.setAttribute('x2', target.x + 100);
        line.setAttribute('y2', target.y + 75);
      }
    }
  });
}

// Zoom and pan controls
function zoom(factor) {
  state.transform.scale *= factor;
  state.transform.scale = Math.max(0.3, Math.min(3, state.transform.scale));
  applyTransform();
}

function resetTransform() {
  state.transform = { x: 0, y: 0, scale: 1 };
  applyTransform();
}

function applyTransform() {
  nodesContainer.style.transform = 
    `translate(${state.transform.x}px, ${state.transform.y}px) scale(${state.transform.scale})`;
  
  svgElement.style.transform = 
    `translate(${state.transform.x}px, ${state.transform.y}px) scale(${state.transform.scale})`;
  
  // Update level of detail
  updatePositions();
}

function startPan(e) {
  if (e.target.closest('.cw-asn-card')) return;
  
  state.isDragging = true;
  state.dragStart = {
    x: e.clientX - state.transform.x,
    y: e.clientY - state.transform.y,
  };
  
  e.target.style.cursor = 'grabbing';
}

function doPan(e) {
  if (!state.isDragging) return;
  
  state.transform.x = e.clientX - state.dragStart.x;
  state.transform.y = e.clientY - state.dragStart.y;
  applyTransform();
}

function endPan(e) {
  state.isDragging = false;
  e.target.style.cursor = '';
}

// Stats and utility functions
function updateStats() {
  statAsnCount.textContent = state.nodes.length;
  statEdgeCount.textContent = state.edges.length;
  
  const totalTraffic = state.nodes.reduce((sum, n) => sum + (n.measurement_count || 0), 0);
  statTotalTraffic.textContent = formatNumber(totalTraffic);
}

function formatNumber(num) {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
  return num.toString();
}

function resetView() {
  closeDetailPanel();
  resetTransform();
  state.viewMode = 'top';
  setViewMode('top');
  
  document.getElementById('sort-by').value = 'traffic';
  document.getElementById('limit').value = '20';
  document.getElementById('country-filter').value = '';
}

function clearTopology() {
  state.nodes = [];
  state.edges = [];
  nodesContainer.innerHTML = '';
  edgesGroup.innerHTML = '';
  updateStats();
}

function showLoading(show) {
  if (show) {
    loadingOverlay.classList.remove('hidden');
  } else {
    loadingOverlay.classList.add('hidden');
  }
}
