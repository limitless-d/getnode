import { fetchHandler } from './src/fetchHandler.js';

/**
 * Cloudflare Workers 的主入口。
 * 将 fetchHandler 暴露为全局 fetch 方法。
 * @param {Request} request - 传入的 HTTP 请求对象。
 * @param {ExecutionContext} env - 环境变量对象，包含部署时设置的变量。
 * @param {ExecutionContext} ctx - 执行上下文对象。
 * @returns {Promise<Response>} - 返回 HTTP 响应。
 */
export default {
    async fetch(request, env, ctx) {
        return fetchHandler(request, env, ctx);
    }
};