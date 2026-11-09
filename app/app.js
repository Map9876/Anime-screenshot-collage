(function () {
  'use strict';
  const S = window.Stitch;
  const $ = s => document.querySelector(s);
  const fileInput = $('#file');
  let blend = 'mean';

  const EXAMPLES = [
    {
      id: 'asuna', title: '亚丝娜 · 镜头 1',
      desc: '6 帧垂直摇镜 + 四周 letterbox 黑边。自动裁边 → 相位相关两两估计 → 最大生成树布局 → 羽化平均。',
      inputs: ['examples/asuna-1.jpg', 'examples/asuna-2.jpg', 'examples/asuna-3.jpg',
        'examples/asuna-4.jpg', 'examples/asuna-5.jpg', 'examples/asuna-6.jpg'],
      ref: 'examples/ref-asuna.jpg', blend: 'mean'
    },
    {
      id: 'totoro', title: '龙猫 · 斜向 pan + 运动汽车',
      desc: '4 帧斜向运镜、画面里有运动的车。中值融合自动把只在少数帧出现的车与固定台标当离群值滤掉。',
      inputs: ['examples/totoro-1.jpg', 'examples/totoro-2.jpg',
        'examples/totoro-3.jpg', 'examples/totoro-4.jpg'],
      ref: 'examples/ref-totoro.jpg', blend: 'median'
    },
    {
      id: 'kiss', title: '男女主接吻 · 垂直三段',
      desc: '三张上 / 中 / 下三段截图，重叠很小。轴对齐扫描 + 相位相关找回大幅垂直位移，零形状扭曲。',
      inputs: ['examples/kiss-1.jpg', 'examples/kiss-2.jpg', 'examples/kiss-3.jpg'],
      ref: 'examples/ref-kiss.jpg', blend: 'mean'
    }
  ];

  const setStatus = t => { $('#status').textContent = t; };

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => resolve(im);
      im.onerror = () => reject(new Error('图片加载失败：' + src));
      im.src = src;
    });
  }

  function toPixels(im, maxW) {
    const w0 = im.naturalWidth || im.width, h0 = im.naturalHeight || im.height;
    const s = Math.min(1, (maxW || 1000) / w0);
    const w = Math.max(1, Math.round(w0 * s)), h = Math.max(1, Math.round(h0 * s));
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(im, 0, 0, w, h);
    return { w, h, data: ctx.getImageData(0, 0, w, h).data };
  }

  async function filesToImages(files) {
    const out = [];
    for (const f of files) {
      if (!f.type || f.type.indexOf('image/') !== 0) continue;
      const url = URL.createObjectURL(f);
      try { out.push(toPixels(await loadImage(url))); }
      finally { URL.revokeObjectURL(url); }
    }
    return out;
  }

  async function urlsToImages(urls) {
    const out = [];
    for (const u of urls) out.push(toPixels(await loadImage(u), 720));
    return out;
  }

  function putCanvas(holder, image) {
    const c = document.createElement('canvas');
    c.width = image.w; c.height = image.h;
    c.getContext('2d').putImageData(new ImageData(image.data, image.w, image.h), 0, 0);
    holder.innerHTML = '';
    holder.appendChild(c);
    return c;
  }

  function diagText(d) {
    const shifts = d.pairs.filter(p => p.j === p.i + 1)
      .map(p => `F${p.i + 1}→F${p.j + 1} (${p.dx},${p.dy})`).join('  ');
    return `输入 ${d.frames} 张 ${d.croppedSizes.map(s => s.join('×')).join(' ')}\n`
      + `输出 ${d.output.join('×')} · ${d.blend === 'median' ? '中值' : '羽化平均'} · ${d.ms} ms · 未覆盖 ${d.holePct}%\n`
      + `相邻位移 ${shifts}\n`
      + `布局 ${d.positions.map(p => `(${p[0]},${p[1]})`).join(' ')}`;
  }

  function progress(st, a, b) {
    if (st === 'fft') setStatus(`FFT ${a}/${b}`);
    else if (st === 'pair') setStatus(`估计位移 ${a}/${b}`);
    else if (st === 'fuse') setStatus(`融合 ${a}/${b}`);
  }

  async function runUpload(files) {
    if (!files || !files.length) return;
    setStatus('读取图片…');
    try {
      const images = await filesToImages(files);
      if (images.length < 2) { setStatus('至少需要 2 张截图'); return; }
      setStatus(`开始计算 ${images.length} 张…`);
      const r = await S.process(images, { blend, onProgress: progress });
      const holder = $('#result');
      const c = putCanvas(holder, r.image);
      const a = document.createElement('a');
      a.className = 'dl'; a.textContent = '下载 PNG';
      a.href = c.toDataURL('image/png'); a.download = 'collage.png';
      holder.appendChild(a);
      $('#diag').textContent = diagText(r.diag);
      setStatus('完成 · 点击屏幕任意处可重新上传');
    } catch (e) {
      setStatus('失败：' + e.message);
    }
  }

  $('#hero').addEventListener('click', e => {
    if (e.target.closest('button, a, input, canvas')) return;
    fileInput.click();
  });
  fileInput.addEventListener('change', () => {
    runUpload(Array.from(fileInput.files));
    fileInput.value = '';
  });
  document.addEventListener('dragover', e => e.preventDefault());
  document.addEventListener('drop', e => {
    e.preventDefault();
    runUpload(Array.from(e.dataTransfer.files || []));
  });
  document.addEventListener('paste', e => {
    const fs = Array.from(e.clipboardData.files || []).filter(f => f.type.indexOf('image/') === 0);
    if (fs.length) { e.preventDefault(); runUpload(fs); }
  });
  document.querySelectorAll('.opts button').forEach(b => {
    b.addEventListener('click', e => {
      e.stopPropagation();
      blend = b.dataset.blend;
      document.querySelectorAll('.opts button').forEach(x => x.classList.toggle('on', x === b));
    });
  });

  function renderCards() {
    const box = $('#cards');
    EXAMPLES.forEach(ex => {
      const card = document.createElement('article');
      card.className = 'card';
      card.innerHTML = `
        <h3>${ex.title}</h3>
        <p class="desc">${ex.desc}</p>
        <div class="inputs">${ex.inputs.map(u => `<img src="${u}" loading="lazy" alt="输入">`).join('')}</div>
        <button type="button" class="run">运行网页版拼接 →</button>
        <div class="compare">
          <figure><figcaption>网页版实时输出</figcaption>
            <div class="out"><span class="ph">尚未运行</span></div></figure>
          <figure><figcaption>Python 完整版参考（含 LaMa 清理）</figcaption>
            <img src="${ex.ref}" loading="lazy" alt="参考输出"></figure>
        </div>
        <pre class="diag"></pre>`;
      box.appendChild(card);
      const btn = card.querySelector('.run');
      const out = card.querySelector('.out');
      const diag = card.querySelector('.diag');
      btn.addEventListener('click', async () => {
        btn.disabled = true; btn.textContent = '计算中…';
        out.innerHTML = '<span class="ph">计算中…</span>';
        try {
          const images = await urlsToImages(ex.inputs);
          const r = await S.process(images, {
            blend: ex.blend,
            onProgress: (st, a, b) => { if (st === 'fuse') btn.textContent = `融合 ${a}/${b}…`; }
          });
          putCanvas(out, r.image);
          diag.textContent = diagText(r.diag);
        } catch (e) {
          out.innerHTML = '';
          diag.textContent = '失败：' + e.message;
        } finally {
          btn.disabled = false; btn.textContent = '再跑一次 ↻';
        }
      });
    });
  }

  renderCards();
})();
