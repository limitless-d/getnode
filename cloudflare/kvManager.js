/**
 * 处理 KV 存储的 HTTP 请求
 * @param {Request} request - HTTP 请求对象
 * @param {ExecutionContext} env - 环境变量对象，包含 KV 命名空间
 * @param {string} txt - KV 存储的键名，默认为 'ADD.txt'
 * @returns {Promise<Response>} - 返回 HTTP 响应
 */
export async function handleKVRequest(request, env, txt = 'ADD.txt') {
    try {
        // 处理 POST 请求：保存数据到 KV
        if (request.method === "POST") {
            if (!env.KV) return new Response("未绑定 KV 空间", { status: 400 });
            try {
                const content = await request.text();
                await env.KV.put(txt, content);
                return new Response("保存成功");
            } catch (error) {
                console.error('保存 KV 时发生错误:', error);
                return new Response("保存失败: " + error.message, { status: 500 });
            }
        }

        // 处理 GET 请求：读取数据从 KV
        let content = '';
        const hasKV = !!env.KV;

        if (hasKV) {
            try {
                content = await env.KV.get(txt) || '';
            } catch (error) {
                console.error('读取 KV 时发生错误:', error);
                content = '读取数据时发生错误: ' + error.message;
            }
        }

        // 返回 HTML 页面，用于显示和编辑 KV 数据
        const html = generateKVEditorHTML(content);
        return new Response(html, {
            headers: { "Content-Type": "text/html;charset=utf-8" }
        });
    } catch (error) {
        console.error('处理 KV 请求时发生错误:', error);
        return new Response("服务器错误: " + error.message, {
            status: 500,
            headers: { "Content-Type": "text/plain;charset=utf-8" }
        });
    }
}

/**
 * 迁移 KV 数据
 * @param {ExecutionContext} env - 环境变量对象，包含 KV 命名空间
 * @param {string} txt - KV 存储的键名，默认为 'ADD.txt'
 * @returns {Promise<boolean>} - 返回迁移是否成功
 */
export async function migrateKVData(env, txt = 'ADD.txt') {
    const oldData = await env.KV.get(`/${txt}`);
    const newData = await env.KV.get(txt);

    if (oldData && !newData) {
        // 写入新位置
        await env.KV.put(txt, oldData);
        // 删除旧数据
        await env.KV.delete(`/${txt}`);
        return true;
    }
    return false;
}

/**
 * 生成 KV 编辑器的 HTML 页面
 * @param {string} content - KV 存储的内容
 * @returns {string} - 返回 HTML 字符串
 */
function generateKVEditorHTML(content) {
    return `
        <!DOCTYPE html>
        <html>
        <head>
            <title>优选订阅列表</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    margin: 0;
                    padding: 15px;
                    box-sizing: border-box;
                    font-size: 13px;
                }
                .editor-container {
                    width: 100%;
                    max-width: 100%;
                    margin: 0 auto;
                }
                .editor {
                    width: 100%;
                    height: 520px;
                    margin: 15px 0;
                    padding: 10px;
                    box-sizing: border-box;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    font-size: 13px;
                    line-height: 1.5;
                    overflow-y: auto;
                    resize: none;
                }
                .save-container {
                    margin-top: 8px;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }
                .save-btn, .back-btn {
                    padding: 6px 15px;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                }
                .save-btn {
                    background: #4CAF50;
                }
                .save-btn:hover {
                    background: #45a049;
                }
                .back-btn {
                    background: #666;
                }
                .back-btn:hover {
                    background: #555;
                }
                .save-status {
                    color: #666;
                }
            </style>
        </head>
        <body>
            <div class="editor-container">
                <textarea class="editor" id="content">${content}</textarea>
                <div class="save-container">
                    <button class="back-btn" onclick="goBack()">返回</button>
                    <button class="save-btn" onclick="saveContent(this)">保存</button>
                    <span class="save-status" id="saveStatus"></span>
                </div>
            </div>
            <script>
                function goBack() {
                    window.history.back();
                }

                function saveContent(button) {
                    const textarea = document.getElementById('content');
                    const content = textarea.value;
                    button.disabled = true;
                    fetch(window.location.href, {
                        method: 'POST',
                        body: content,
                        headers: { 'Content-Type': 'text/plain;charset=UTF-8' }
                    })
                    .then(response => {
                        if (!response.ok) throw new Error('保存失败');
                        document.getElementById('saveStatus').textContent = '保存成功';
                    })
                    .catch(error => {
                        console.error('保存失败:', error);
                        document.getElementById('saveStatus').textContent = '保存失败';
                    })
                    .finally(() => {
                        button.disabled = false;
                    });
                }
            </script>
        </body>
        </html>
    `;
}