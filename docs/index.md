---
layout: home
title: 免费节点列表
---

<div id="nodes">
  <p>正在加载节点...</p>
</div>

<script>
fetch('/nodes.json')
  .then(response => response.json())
  .then(data => {
    let html = '<ul>';
    data.forEach(node => {
      html += `<li>${node.server}:${node.port} (协议: ${node.type})</li>`;
    });
    html += '</ul>';
    document.getElementById('nodes').innerHTML = html;
  });
</script>
