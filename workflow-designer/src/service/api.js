import axios from "axios";

const STORAGE_KEY = 'server_config';
export const defaultIp = '127.0.0.1';
export const defaultPort = '9080';

export const getBaseUrl = () => {
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        const config = saved ? JSON.parse(saved) : {};
        const ip = config.ip || defaultIp;
        const port = config.port || defaultPort;
        console.log(`http://${ip}:${port}`);
        return `http://${ip}:${port}`;
    } catch (e) {
        return `http://${defaultIp}:${defaultPort}`;
    }
}

const api = axios.create({timeout: 10000});

api.interceptors.response.use(
    (response) => response.data?.data || response.data,
    (error) => Promise.reject(error)
);

export async function getAgentCards() {
    return api.get(`${getBaseUrl()}/rest/agents/agentcards`);
}

export async function getWorkflow() {
    return api.get(`${getBaseUrl()}/rest/agents/workflow/query`);
}

export async function createWorkflow(data) {
    return api.post(`${getBaseUrl()}/rest/agents/workflow/create`, data);
}

export async function switchLanguage(local) {
    return axios.post(`${getBaseUrl()}/rest/agents/switch-language?scenario='5g'`, {
        language: local,
    })
}

