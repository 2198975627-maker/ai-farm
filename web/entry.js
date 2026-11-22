import * as THREE from "three";

const HERO_PHOTO_URL =
  "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=2000&q=85";

const AI_VENDORS = [
  {
    title: "OpenAI",
    sub: "GPT-4o · o3 · Codex · 经理层强推理",
    badge: "O",
    icon: "/icons/openai.png",
    bg: "https://images.unsplash.com/photo-1639322537228-f710d846310a?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "Google Gemini",
    sub: "Gemini 2.5 Pro / Flash · 多模态长文本",
    badge: "G",
    icon: "/icons/gemini.svg",
    bg: "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "Anthropic",
    sub: "Claude 4 / Sonnet · 架构审查与精细编码",
    badge: "A",
    icon: "/icons/anthropic.png",
    bg: "https://images.unsplash.com/photo-1507608616759-54f48f0af0ee?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "xAI",
    sub: "Grok 3 · 实时推理与高速探索",
    badge: "X",
    icon: "/icons/grok.png",
    bg: "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "DeepSeek",
    sub: "DeepSeek R1 / V3 · 高性价比深度思考",
    badge: "D",
    icon: "/icons/deepseek.png",
    bg: "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "Alibaba Qwen",
    sub: "通义千问 Qwen · 全栈开源与代码执行",
    badge: "Q",
    icon: "/icons/qwen.png",
    bg: "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "Meta Llama",
    sub: "Llama 4 · 全球开源生态基座",
    badge: "M",
    icon: null,
    bg: "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "Mistral AI",
    sub: "Mistral Large · 轻量高速欧洲前沿模型",
    badge: "M",
    icon: null,
    bg: "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "Moonshot Kimi",
    sub: "Kimi · 超长上下文研读与检索",
    badge: "K",
    icon: "/icons/kimi.png",
    bg: "https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=720&q=80"
  },
  {
    title: "Zhipu GLM",
    sub: "智谱 GLM-4 · 中文理解与工具调用",
    badge: "Z",
    icon: "/icons/glm.png",
    bg: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=720&q=80"
  }
];

function createStageDOM() {
  const stage = document.createElement("div");
  stage.id = "farmEntryStage";
  stage.innerHTML = `
    <canvas id="farmEntryCanvas"></canvas>

    <section id="farmEntryHome" aria-label="AI Farm 空间入口">
      <div class="fe-hero-wrap" id="feHeroWrap">
        <img
          class="fe-hero-photo"
          id="feHeroPhoto"
          src="${HERO_PHOTO_URL}"
          alt="AI Farm 现代建筑光影空间"
          crossorigin="anonymous"
          draggable="false"
        />
      </div>
      <div class="fe-hero-grade"></div>
      <button class="fe-skip-btn" id="farmEntrySkipBtn" type="button">跳过入场 →</button>

      <div class="fe-home-content" id="feHomeContent">
        <div class="fe-eyebrow">AI FARM · MULTI-MODEL STUDIO</div>
        <h1 class="fe-title">AI FARM</h1>
        <p class="fe-subtitle">把想法，变成能用的东西。</p>
        <button id="farmEntryPortalBtn" type="button" aria-label="进入 AI Farm 3D 空间">
          <span class="fe-portal-zh">进入 AI Farm</span>
          <span class="fe-portal-en">ENTER</span>
        </button>
      </div>
    </section>

    <section id="farmEntryWorld" aria-label="Farm World 全球模型矩阵">
      <div class="fe-world-header">
        <h2 class="fe-world-title">FARM WORLD</h2>
        <p class="fe-world-hint" id="feWorldHint">长按拖动探索 · 点击地心进入 AI Farm</p>
      </div>
      <button class="fe-hud-btn" id="farmEntryBackBtn" type="button">← 回首页</button>
      <button class="fe-hud-btn" id="farmEntryWorldSkipBtn" type="button">跳过入场 →</button>
      <div class="fe-toast" id="farmEntryToast"></div>
    </section>

    <div class="fe-vignette"></div>
    <div id="farmEntryFlash"></div>
    <div class="fe-grain"></div>
  `;
  document.body.appendChild(stage);
  return stage;
}

function launchFarmEntry() {
  if (document.getElementById("farmEntryStage")) return;
  window.__farmEntryActive = true;

  const stage = createStageDOM();
  const canvas = document.getElementById("farmEntryCanvas");
  const heroWrap = document.getElementById("feHeroWrap");
  const homeContent = document.getElementById("feHomeContent");
  const portalBtn = document.getElementById("farmEntryPortalBtn");
  const skipBtn = document.getElementById("farmEntrySkipBtn");
  const worldSkipBtn = document.getElementById("farmEntryWorldSkipBtn");
  const worldEl = document.getElementById("farmEntryWorld");
  const worldHintEl = document.getElementById("feWorldHint");
  const backBtn = document.getElementById("farmEntryBackBtn");
  const flashOverlay = document.getElementById("farmEntryFlash");
  const toastEl = document.getElementById("farmEntryToast");

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isSmallScreen = window.innerWidth < 768;

  let currentScene = "home"; // "home" | "entering" | "world" | "leaving" | "enteringOffice" | "closed"
  let transitionStart = 0;
  const ENTER_DURATION = reduceMotion ? 450 : 1220;
  const LEAVE_DURATION = reduceMotion ? 400 : 900;
  const CORE_DIVE_DURATION = reduceMotion ? 400 : 1150;

  let toastTimer = null;
  function showToast(msg, duration = 2600) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    if (duration > 0) {
      toastTimer = setTimeout(() => toastEl.classList.remove("show"), duration);
    }
  }

  let homeMouseX = 0, homeMouseY = 0;
  let homeLerpX = 0, homeLerpY = 0;
  function onWindowPointerMove(e) {
    if (currentScene !== "home") return;
    homeMouseX = (e.clientX / window.innerWidth - 0.5) * 2;
    homeMouseY = (e.clientY / window.innerHeight - 0.5) * 2;
  }
  window.addEventListener("pointermove", onWindowPointerMove, { passive: true });

  // Three.js Setup (with graceful fallback if WebGL is unavailable)
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      powerPreference: "high-performance",
      alpha: false
    });
  } catch (_) {
    window.__farmEntryActive = false;
    window.removeEventListener("pointermove", onWindowPointerMove);
    stage.remove();
    window.dispatchEvent(new Event("farmEntryClosed"));
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.06;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x060709);
  scene.fog = new THREE.FogExp2(0x060709, 0.044);

  const BASE_CAM_Z = 11.6;
  const BASE_FOV = 46;
  const camera = new THREE.PerspectiveCamera(BASE_FOV, window.innerWidth / window.innerHeight, 0.1, 120);
  camera.position.set(0, 0, BASE_CAM_Z);

  scene.add(new THREE.AmbientLight(0xffffff, 0.88));
  const warmCoreLight = new THREE.PointLight(0xe8c58a, 2.2, 24, 1.5);
  scene.add(warmCoreLight);
  const rimLight = new THREE.DirectionalLight(0xf5efe4, 0.9);
  rimLight.position.set(5, 7, 9);
  scene.add(rimLight);

  const worldGroup = new THREE.Group();
  scene.add(worldGroup);

  // Central Glowing Wireframe Globe
  const globeGroup = new THREE.Group();
  worldGroup.add(globeGroup);
  const GLOBE_R = 2.15;

  function buildCirclePoints(radius, segments) {
    const pts = [];
    for (let i = 0; i <= segments; i++) {
      const a = (i / segments) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
    }
    return pts;
  }

  const lineMatLat = new THREE.LineBasicMaterial({ color: 0xf7f4ee, transparent: true, opacity: 0.16 });
  const lineMatLon = new THREE.LineBasicMaterial({ color: 0xe8c58a, transparent: true, opacity: 0.13 });

  for (let i = -3; i <= 3; i++) {
    const lat = (i / 4) * (Math.PI * 0.48);
    const geo = new THREE.BufferGeometry().setFromPoints(buildCirclePoints(Math.cos(lat) * GLOBE_R, 72));
    const ring = new THREE.Line(geo, lineMatLat);
    ring.position.y = Math.sin(lat) * GLOBE_R;
    globeGroup.add(ring);
  }

  const lonGeo = new THREE.BufferGeometry().setFromPoints(buildCirclePoints(GLOBE_R, 72));
  for (let i = 0; i < 10; i++) {
    const ring = new THREE.Line(lonGeo, lineMatLon);
    ring.rotation.z = Math.PI / 2;
    ring.rotation.y = (i / 10) * Math.PI;
    globeGroup.add(ring);
  }

  const icoWire = new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(GLOBE_R * 0.56, 1));
  globeGroup.add(new THREE.LineSegments(icoWire, new THREE.LineBasicMaterial({ color: 0xe8c58a, transparent: true, opacity: 0.14 })));

  function createGlowTexture() {
    const c = document.createElement("canvas");
    c.width = 256;
    c.height = 256;
    const ctx = c.getContext("2d");
    const g = ctx.createRadialGradient(128, 128, 4, 128, 128, 126);
    g.addColorStop(0, "rgba(255, 244, 222, 0.72)");
    g.addColorStop(0.28, "rgba(232, 197, 138, 0.28)");
    g.addColorStop(0.65, "rgba(232, 197, 138, 0.06)");
    g.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 256, 256);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  const coreGlow = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: createGlowTexture(),
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    })
  );
  coreGlow.scale.set(4.8, 4.8, 1);
  globeGroup.add(coreGlow);

  // Luminous Earth Core Nucleus + Raycast Hit Sphere
  const coreNucleusMat = new THREE.MeshBasicMaterial({
    color: 0xfff2d6,
    transparent: true,
    opacity: 0.78
  });
  const coreNucleus = new THREE.Mesh(new THREE.SphereGeometry(0.28, 24, 24), coreNucleusMat);
  globeGroup.add(coreNucleus);

  const coreHitMesh = new THREE.Mesh(
    new THREE.SphereGeometry(GLOBE_R * 0.65, 20, 20),
    new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
  );
  coreHitMesh.userData.isGlobeCore = true;
  globeGroup.add(coreHitMesh);

  // Portal Rings
  const portalGroup = new THREE.Group();
  scene.add(portalGroup);
  const portalTorusMat = new THREE.MeshBasicMaterial({ color: 0xfff3dc, transparent: true, opacity: 0 });
  const portalRing = new THREE.Mesh(new THREE.TorusGeometry(2.1, 0.025, 16, 100), portalTorusMat);
  portalRing.position.z = 8.4;
  portalGroup.add(portalRing);

  const portalOuterMat = new THREE.MeshBasicMaterial({ color: 0xe8c58a, transparent: true, opacity: 0 });
  const portalOuterRing = new THREE.Mesh(new THREE.TorusGeometry(2.45, 0.012, 12, 100), portalOuterMat);
  portalOuterRing.position.z = 8.0;
  portalGroup.add(portalOuterRing);

  // Particles
  const PARTICLE_COUNT = isSmallScreen ? 90 : 170;
  const pPositions = new Float32Array(PARTICLE_COUNT * 3);
  const pBasePositions = new Float32Array(PARTICLE_COUNT * 3);
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const r = 3.2 + Math.random() * 11;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    pPositions[i * 3] = pBasePositions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pPositions[i * 3 + 1] = pBasePositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    pPositions[i * 3 + 2] = pBasePositions[i * 3 + 2] = r * Math.cos(phi);
  }
  const particleGeo = new THREE.BufferGeometry();
  particleGeo.setAttribute("position", new THREE.BufferAttribute(pPositions, 3));
  worldGroup.add(
    new THREE.Points(
      particleGeo,
      new THREE.PointsMaterial({ color: 0xf7efe0, size: 0.055, transparent: true, opacity: 0.52, depthWrite: false })
    )
  );

  // Rounded 3D AI Vendor Cards
  function createRoundedRectGeometry(width, height, radius) {
    const shape = new THREE.Shape();
    const x = -width / 2;
    const y = -height / 2;
    shape.moveTo(x + radius, y);
    shape.lineTo(x + width - radius, y);
    shape.quadraticCurveTo(x + width, y, x + width, y + radius);
    shape.lineTo(x + width, y + height - radius);
    shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    shape.lineTo(x + radius, y + height);
    shape.quadraticCurveTo(x, y + height, x, y + height - radius);
    shape.lineTo(x, y + radius);
    shape.quadraticCurveTo(x, y, x + radius, y);

    const geo = new THREE.ShapeGeometry(shape, 10);
    const pos = geo.attributes.position;
    const uvs = new Float32Array(pos.count * 2);
    for (let i = 0; i < pos.count; i++) {
      uvs[i * 2] = (pos.getX(i) - x) / width;
      uvs[i * 2 + 1] = (pos.getY(i) - y) / height;
    }
    geo.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
    return geo;
  }

  function drawVendorCardCanvas(ctx, w, h, item, bgImg, iconImg) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#12141a";
    ctx.fillRect(0, 0, w, h);

    if (bgImg && bgImg.complete && bgImg.naturalWidth > 0) {
      const imgRatio = bgImg.naturalWidth / bgImg.naturalHeight;
      const boxRatio = w / h;
      let sx = 0, sy = 0, sw = bgImg.naturalWidth, sh = bgImg.naturalHeight;
      if (imgRatio > boxRatio) {
        sw = bgImg.naturalHeight * boxRatio;
        sx = (bgImg.naturalWidth - sw) * 0.5;
      } else {
        sh = bgImg.naturalWidth / boxRatio;
        sy = (bgImg.naturalHeight - sh) * 0.5;
      }
      ctx.drawImage(bgImg, sx, sy, sw, sh, 0, 0, w, h);
    }

    // Dark gradient overlay for legibility
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "rgba(7, 8, 10, 0.25)");
    grad.addColorStop(0.5, "rgba(7, 8, 10, 0.42)");
    grad.addColorStop(1, "rgba(7, 8, 10, 0.92)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);

    // Subtle hairline border
    ctx.strokeStyle = "rgba(255, 255, 255, 0.18)";
    ctx.lineWidth = 3;
    ctx.strokeRect(1.5, 1.5, w - 3, h - 3);

    // Top-left circular vendor icon medallion
    const cx = 56, cy = 56, r = 28;
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255, 255, 255, 0.94)";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(232, 197, 138, 0.65)";
    ctx.stroke();
    ctx.clip();

    if (iconImg && iconImg.complete && iconImg.naturalWidth > 0) {
      const pad = 8;
      ctx.drawImage(iconImg, cx - r + pad, cy - r + pad, (r - pad) * 2, (r - pad) * 2);
    } else {
      ctx.fillStyle = "#12141a";
      ctx.font = '600 24px "Inter", sans-serif';
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(item.badge, cx, cy + 1);
    }
    ctx.restore();

    // Vendor Title & Model Subtitle
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillStyle = "#fbf8f3";
    ctx.font = '600 30px "Inter", "Noto Sans SC", "PingFang SC", sans-serif';
    ctx.shadowColor = "rgba(0, 0, 0, 0.72)";
    ctx.shadowBlur = 10;
    ctx.fillText(item.title, 26, h - 46);

    ctx.fillStyle = "rgba(232, 197, 138, 0.92)";
    ctx.font = '400 17px "Inter", "Noto Sans SC", "PingFang SC", sans-serif';
    ctx.fillText(item.sub, 26, h - 20);
    ctx.shadowBlur = 0;
  }

  const cardGeo = createRoundedRectGeometry(1.82, 1.22, 0.09);
  const cardsGroup = new THREE.Group();
  worldGroup.add(cardsGroup);

  const cardEntries = [];
  const SPHERE_R = 4.68;
  const N = AI_VENDORS.length;

  AI_VENDORS.forEach((item, i) => {
    const y = 1 - (i / (N - 1)) * 2;
    const rad = Math.sqrt(Math.max(0, 1 - y * y));
    const th = 2.3999632 * i;
    const basePos = new THREE.Vector3(
      Math.cos(th) * rad * SPHERE_R,
      y * SPHERE_R * 0.82,
      Math.sin(th) * rad * SPHERE_R
    );

    const c = document.createElement("canvas");
    c.width = 640;
    c.height = 430;
    const ctx = c.getContext("2d");

    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 4);

    const mat = new THREE.MeshStandardMaterial({
      map: tex,
      roughness: 0.55,
      metalness: 0.06,
      emissive: new THREE.Color(0x000000),
      emissiveIntensity: 0,
      transparent: true,
      opacity: 1,
      side: THREE.DoubleSide
    });

    const mesh = new THREE.Mesh(cardGeo, mat);
    mesh.position.copy(basePos);
    cardsGroup.add(mesh);

    const bgImg = new Image();
    bgImg.crossOrigin = "anonymous";
    const iconImg = item.icon ? new Image() : null;

    const redraw = () => {
      drawVendorCardCanvas(ctx, c.width, c.height, item, bgImg, iconImg);
      tex.needsUpdate = true;
    };
    redraw();

    bgImg.onload = redraw;
    bgImg.src = item.bg;
    if (iconImg) {
      iconImg.onload = redraw;
      iconImg.src = item.icon;
    }

    const entry = {
      data: item,
      mesh,
      mat,
      basePos: basePos.clone(),
      normal: basePos.clone().normalize(),
      phase: Math.random() * Math.PI * 2,
      hoverLerp: 0
    };
    mesh.userData.cardEntry = entry;
    cardEntries.push(entry);
  });

  // Orbit & Focus Controls
  let rotX = -0.18, rotY = 0.45;
  let targetRotX = -0.18, targetRotY = 0.45;
  let velX = 0, velY = reduceMotion ? 0 : 0.0014;
  let isDragging = false;
  let lastPtrX = 0, lastPtrY = 0;
  let dragDistance = 0;

  const raycaster = new THREE.Raycaster();
  const pointerNDC = new THREE.Vector2(-99, -99);
  let hoveredCard = null;
  let hoveredCore = false;
  let focusedCard = null;
  let diveStartCamPos = new THREE.Vector3();

  const camPosCurrent = new THREE.Vector3(0, 0, BASE_CAM_Z);
  const camLookCurrent = new THREE.Vector3(0, 0, 0);
  const camPosTarget = new THREE.Vector3(0, 0, BASE_CAM_Z);
  const camLookTarget = new THREE.Vector3(0, 0, 0);

  function focusOnCard(entry) {
    if (focusedCard === entry) {
      clearFocus();
      return;
    }
    focusedCard = entry;
    worldGroup.updateMatrixWorld(true);
    const wp = entry.mesh.getWorldPosition(new THREE.Vector3());
    const dir = wp.clone().normalize();
    camPosTarget.copy(wp).addScaledVector(dir, 3.15);
    camLookTarget.copy(wp);
    showToast(`${entry.data.title} — ${entry.data.sub}`, 0);
  }

  function clearFocus() {
    if (!focusedCard) return;
    focusedCard = null;
    camPosTarget.set(0, 0, BASE_CAM_Z);
    camLookTarget.set(0, 0, 0);
    toastEl.classList.remove("show");
  }

  canvas.addEventListener("pointerdown", (e) => {
    if (currentScene !== "world") return;
    isDragging = true;
    lastPtrX = e.clientX;
    lastPtrY = e.clientY;
    dragDistance = 0;
    canvas.setPointerCapture(e.pointerId);
  });

  canvas.addEventListener("pointermove", (e) => {
    pointerNDC.x = (e.clientX / window.innerWidth) * 2 - 1;
    pointerNDC.y = -(e.clientY / window.innerHeight) * 2 + 1;
    if (!isDragging || currentScene !== "world") return;
    const dx = e.clientX - lastPtrX;
    const dy = e.clientY - lastPtrY;
    lastPtrX = e.clientX;
    lastPtrY = e.clientY;
    dragDistance += Math.hypot(dx, dy);
    if (focusedCard && dragDistance > 12) clearFocus();
    velY = dx * 0.0052;
    velX = dy * 0.0042;
    targetRotY += velY;
    targetRotX = Math.max(-1.05, Math.min(1.05, targetRotX + velX));
  });

  canvas.addEventListener("pointerup", (e) => {
    if (!isDragging) return;
    isDragging = false;
    try { canvas.releasePointerCapture(e.pointerId); } catch (_) {}
    if (dragDistance < 6 && currentScene === "world") {
      raycaster.setFromCamera(pointerNDC, camera);
      const targets = [...cardsGroup.children, coreHitMesh];
      const hits = raycaster.intersectObjects(targets, false);
      if (hits.length > 0) {
        if (hits[0].object.userData.cardEntry) {
          focusOnCard(hits[0].object.userData.cardEntry);
        } else if (hits[0].object.userData.isGlobeCore) {
          startCoreDive();
        }
      } else {
        clearFocus();
      }
    }
  });

  function enterWorld() {
    if (currentScene !== "home") return;
    currentScene = "entering";
    transitionStart = performance.now();
    stage.classList.add("entering");
    clearFocus();
  }

  function backToHome() {
    if (currentScene !== "world") return;
    clearFocus();
    currentScene = "leaving";
    transitionStart = performance.now();
    stage.classList.remove("world-active");
    stage.classList.add("entering");
  }

  let rafId = null;
  let isPageHidden = false;

  function onResize() {
    if (currentScene === "closed") return;
    const w = window.innerWidth;
    const h = window.innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h);
  }

  function onVisibilityChange() {
    isPageHidden = document.hidden;
    if (!isPageHidden && currentScene !== "closed" && !rafId) {
      rafId = requestAnimationFrame(animate);
    } else if (isPageHidden && rafId) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  function startCoreDive() {
    if (currentScene !== "world") return;
    clearFocus();
    currentScene = "enteringOffice";
    transitionStart = performance.now();
    diveStartCamPos.copy(camera.position);
    worldEl.style.opacity = "0";
    worldEl.style.pointerEvents = "none";
    canvas.style.cursor = "default";
  }

  function finishEnterOffice() {
    if (currentScene === "closed") return;
    currentScene = "closed";
    window.__farmEntryActive = false;
    stage.classList.add("entry-closing");
    window.removeEventListener("pointermove", onWindowPointerMove);
    window.removeEventListener("resize", onResize);
    document.removeEventListener("visibilitychange", onVisibilityChange);
    setTimeout(() => {
      if (rafId) cancelAnimationFrame(rafId);
      renderer.dispose();
      stage.remove();
      window.dispatchEvent(new Event("farmEntryClosed"));
    }, 580);
  }

  portalBtn.addEventListener("click", enterWorld);
  backBtn.addEventListener("click", backToHome);
  worldSkipBtn.addEventListener("click", finishEnterOffice);
  skipBtn.addEventListener("click", finishEnterOffice);
  window.addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", onVisibilityChange);

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function animate(now) {
    if (isPageHidden || currentScene === "closed") return;
    rafId = requestAnimationFrame(animate);
    const tSec = now * 0.001;

    if (currentScene === "home") {
      homeLerpX += (homeMouseX - homeLerpX) * 0.06;
      homeLerpY += (homeMouseY - homeLerpY) * 0.06;
      heroWrap.style.transform = `translate3d(${(-homeLerpX * 10).toFixed(2)}px, ${(-homeLerpY * 8).toFixed(2)}px, 0)`;
      homeContent.style.transform = `translate3d(${(-homeLerpX * 22).toFixed(2)}px, ${(-homeLerpY * 16).toFixed(2)}px, 0)`;
      return;
    }

    if (currentScene === "entering") {
      const raw = Math.min((now - transitionStart) / ENTER_DURATION, 1);
      const eased = easeInOutCubic(raw);
      camera.position.set(0, 0, 15.8 + (BASE_CAM_Z - 15.8) * eased);
      camera.lookAt(0, 0, 0);
      camera.fov = BASE_FOV + Math.sin(raw * Math.PI) * 26;
      camera.updateProjectionMatrix();
      worldGroup.scale.setScalar(1.28 - 0.28 * eased);

      portalRing.position.z = 11.2 - raw * 9.5;
      portalOuterRing.position.z = 10.6 - raw * 9.5;
      const ringAlpha = Math.sin(raw * Math.PI) * 0.85;
      portalTorusMat.opacity = ringAlpha;
      portalOuterMat.opacity = ringAlpha * 0.65;

      const flashBell = Math.exp(-Math.pow((raw - 0.48) / 0.14, 2));
      flashOverlay.style.opacity = (flashBell * 0.68).toFixed(3);

      const posAttr = particleGeo.attributes.position;
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        posAttr.array[i * 3 + 2] = pBasePositions[i * 3 + 2] + raw * 12;
      }
      posAttr.needsUpdate = true;

      if (raw >= 1) {
        currentScene = "world";
        flashOverlay.style.opacity = "0";
        portalTorusMat.opacity = 0;
        portalOuterMat.opacity = 0;
        worldGroup.scale.setScalar(1);
        camera.fov = BASE_FOV;
        camera.updateProjectionMatrix();
        camPosCurrent.set(0, 0, BASE_CAM_Z);
        camPosTarget.set(0, 0, BASE_CAM_Z);
        camLookCurrent.set(0, 0, 0);
        camLookTarget.set(0, 0, 0);
        for (let i = 0; i < PARTICLE_COUNT; i++) {
          posAttr.array[i * 3 + 2] = pBasePositions[i * 3 + 2];
        }
        posAttr.needsUpdate = true;
        stage.classList.remove("entering");
        stage.classList.add("world-active");
      }
    }

    if (currentScene === "leaving") {
      const raw = Math.min((now - transitionStart) / LEAVE_DURATION, 1);
      const eased = easeInOutCubic(raw);
      camera.position.set(0, 0, BASE_CAM_Z + eased * 4.4);
      camera.fov = BASE_FOV + Math.sin(raw * Math.PI) * 14;
      camera.updateProjectionMatrix();
      worldGroup.scale.setScalar(1 + eased * 0.22);
      const flashBell = Math.exp(-Math.pow((raw - 0.5) / 0.16, 2));
      flashOverlay.style.opacity = (flashBell * 0.45).toFixed(3);

      if (raw >= 1) {
        currentScene = "home";
        flashOverlay.style.opacity = "0";
        worldGroup.scale.setScalar(1);
        camera.fov = BASE_FOV;
        camera.position.set(0, 0, BASE_CAM_Z);
        camera.updateProjectionMatrix();
        stage.classList.remove("entering", "world-active");
        canvas.style.cursor = "default";
      }
    }

    if (currentScene === "enteringOffice") {
      const raw = Math.min((now - transitionStart) / CORE_DIVE_DURATION, 1);
      const diveEase = raw * raw * raw; // accelerating plunge into the Earth core
      camera.position.lerpVectors(diveStartCamPos, new THREE.Vector3(0, 0, 0.12), diveEase);
      camera.lookAt(0, 0, 0);
      camera.fov = BASE_FOV + diveEase * 46;
      camera.updateProjectionMatrix();

      const coreSwell = 4.8 + diveEase * 16;
      coreGlow.scale.set(coreSwell, coreSwell, 1);
      coreNucleus.scale.setScalar(1 + diveEase * 6.5);
      warmCoreLight.intensity = 2.2 + diveEase * 8.0;

      // Luminous bloom peak as camera pierces the core
      const flashVal = Math.max(0, (raw - 0.55) / 0.45);
      flashOverlay.style.opacity = Math.min(0.96, flashVal * 1.05).toFixed(3);

      if (raw >= 1) {
        finishEnterOffice();
        return;
      }
    }

    if (currentScene === "world" || currentScene === "entering" || currentScene === "leaving" || currentScene === "enteringOffice") {
      if (!isDragging && !focusedCard) {
        const autoSpeed = reduceMotion ? 0 : (currentScene === "enteringOffice" ? 0.008 : 0.0014);
        velY += (autoSpeed - velY) * 0.035;
        velX *= 0.92;
        targetRotY += velY;
        targetRotX = Math.max(-1.05, Math.min(1.05, targetRotX + velX));
      } else if (isDragging) {
        velX *= 0.85;
        velY *= 0.85;
      }

      rotX += (targetRotX - rotX) * 0.085;
      rotY += (targetRotY - rotY) * 0.085;
      worldGroup.rotation.order = "YXZ";
      worldGroup.rotation.y = rotY;
      worldGroup.rotation.x = rotX;
      globeGroup.rotation.y = tSec * 0.08;

      let nextHover = null;
      let nextCoreHover = false;
      if (currentScene === "world" && !isDragging) {
        raycaster.setFromCamera(pointerNDC, camera);
        const hits = raycaster.intersectObjects([...cardsGroup.children, coreHitMesh], false);
        if (hits.length > 0) {
          if (hits[0].object.userData.cardEntry) {
            nextHover = hits[0].object.userData.cardEntry;
          } else if (hits[0].object.userData.isGlobeCore) {
            nextCoreHover = true;
          }
        }
      }
      hoveredCard = nextHover;
      hoveredCore = nextCoreHover;
      if (currentScene === "world") {
        canvas.style.cursor = (hoveredCard || hoveredCore) ? "pointer" : (isDragging ? "grabbing" : "grab");
        const coreTargetScale = hoveredCore ? 1.45 : (1 + Math.sin(tSec * 2.2) * 0.08);
        coreNucleus.scale.lerp(new THREE.Vector3(coreTargetScale, coreTargetScale, coreTargetScale), 0.14);
        const glowTarget = hoveredCore ? 6.2 : 4.8;
        coreGlow.scale.lerp(new THREE.Vector3(glowTarget, glowTarget, 1), 0.12);
        if (worldHintEl) {
          worldHintEl.textContent = hoveredCore
            ? "点击地心 · 进入 AI Farm 工作台"
            : "长按拖动探索 · 点击地心进入 AI Farm";
        }
      }

      cardEntries.forEach((entry) => {
        const isHover = entry === hoveredCard;
        const isFocus = entry === focusedCard;
        entry.hoverLerp += (((isHover || isFocus) ? 1 : 0) - entry.hoverLerp) * 0.12;
        const floatOffset = reduceMotion ? 0 : Math.sin(tSec * 0.9 + entry.phase) * 0.13;
        entry.mesh.position.copy(entry.basePos);
        entry.mesh.position.y += floatOffset;
        entry.mesh.position.addScaledVector(entry.normal, entry.hoverLerp * 0.42);
        entry.mesh.scale.setScalar(1 + entry.hoverLerp * 0.085);
        entry.mat.emissive.setHex(0x2a2114);
        entry.mat.emissiveIntensity = entry.hoverLerp * 0.55;
        const targetAlpha = focusedCard && !isFocus ? 0.32 : 1.0;
        entry.mat.opacity += (targetAlpha - entry.mat.opacity) * 0.1;
        entry.mesh.lookAt(camera.position);
      });

      if (currentScene === "world") {
        if (focusedCard) {
          worldGroup.updateMatrixWorld(true);
          const wp = focusedCard.mesh.getWorldPosition(new THREE.Vector3());
          camPosTarget.copy(wp).addScaledVector(wp.clone().normalize(), 3.15);
          camLookTarget.copy(wp);
        }
        camPosCurrent.lerp(camPosTarget, 0.085);
        camLookCurrent.lerp(camLookTarget, 0.085);
        camera.position.copy(camPosCurrent);
        camera.lookAt(camLookCurrent);
      }
    }

    renderer.render(scene, camera);
  }

  rafId = requestAnimationFrame(animate);
}

window.replayFarmEntry = function () {
  launchFarmEntry();
};

launchFarmEntry();
