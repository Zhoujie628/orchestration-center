import React, { useMemo, useState, useCallback } from 'react';
import {
    CheckCircle2,
    XCircle,
    Loader,
    Clock,
    ChevronRight,
    ChevronDown,
    Bot,
    ArrowRight,
    ArrowLeft,
    MessageSquare,
    GitBranch,
    RotateCcw,
    FileText,
    Shield,
    Bell,
} from 'lucide-react';

/* ──────────────────────────────────────────────────────────────────
 * Event grouping logic (Phase 3.2: groupEventsByStep)
 * ────────────────────────────────────────────────────────────────── */

function groupEventsByStep(events) {
    const steps = new Map();
    let currentStep = null;

    // Build agent -> step mapping from task_request events so that
    // agent_request/agent_response (which lack a step field) can be
    // attributed to the correct step.
    const agentToStep = new Map();

   for (const event of events) {
       const stepName = event.data?.step;
       if (event.type === 'step_start') {
           currentStep = stepName;
           steps.set(stepName, {
               name: stepName,
               status: 'running',
               startTime: event.timestamp,
               endTime: null,
               interactions: [],
               route: null,
               output: null,
               error: null,
               isSelfLoop: false,
           });
       }
        // Track step from task_request: also register agent->step mapping
        else if (event.type === 'task_request' && stepName && event.data?.agent) {
            agentToStep.set(event.data.agent, stepName);
            if (steps.has(stepName)) currentStep = stepName;
        }
        // Track step from event data (handles parallel steps where
        // agent interactions arrive for earlier steps after later ones start)
        else if (stepName && steps.has(stepName)) {
            currentStep = stepName;
        }
        // For events without step field (agent_request, agent_response, etc.),
        // use the agent->step mapping to find the correct step
        else if (!stepName && event.data?.agent && agentToStep.has(event.data.agent)) {
            currentStep = agentToStep.get(event.data.agent);
        }
       if (!currentStep || !steps.has(currentStep)) continue;
       const step = steps.get(currentStep);

        switch (event.type) {
            case 'agent_request':
                step.interactions.push({
                    agent: event.data.agent,
                    request: event.data,
                    response: null,
                    negotiations: [],
                    timestamp: event.timestamp,
                });
                break;
            case 'agent_response': {
                const last = step.interactions.findLast(i => i.agent === event.data.agent && !i.response);
                if (last) last.response = event.data;
                break;
            }
            case 'negotiation_request':
            case 'negotiation_resolved':
            case 'negotiation_failed': {
                const interaction = step.interactions.findLast(i => i.agent === event.data.agent);
                if (interaction) {
                    interaction.negotiations.push(event);
                }
                break;
            }
            case 'authorization_request':
                step.interactions.push({
                    agent: event.data.agent,
                    request: { authorization: true, ...event.data },
                    response: null,
                    negotiations: [],
                    timestamp: event.timestamp,
                });
                break;
            case 'notification':
                step.interactions.push({
                    agent: event.data.agent,
                    request: { notification: true, ...event.data },
                    response: null,
                    negotiations: [],
                    timestamp: event.timestamp,
                });
                break;
            case 'route_decision':
                step.route = event.data;
                break;
            case 'step_complete':
                step.status = 'completed';
                step.endTime = event.timestamp;
                break;
            case 'error':
                step.status = 'failed';
                step.endTime = event.timestamp;
                step.error = event.data;
                break;
            case 'task_status_changed':
                if (event.data?.result && stepName) {
                    step.output = event.data.result;
                }
                break;
        }
    }

    // Mark self-loop steps: only COMPLETED steps with 0 interactions.
    // Running steps may still be waiting for agent_request events to arrive,
    // so marking them as self-loop prematurely is wrong.
    for (const step of steps.values()) {
        if (step.interactions.length === 0 && step.status === 'completed') {
            step.isSelfLoop = true;
        }
    }

    return Array.from(steps.values());
}

/* ──────────────────────────────────────────────────────────────────
 * Step status visualization (Phase 3.6)
 * ────────────────────────────────────────────────────────────────── */

const StepStatusMap = {
    pending:   { icon: Clock,        color: 'text-zinc-400',    dot: 'bg-zinc-300' },
    running:   { icon: Loader,       color: 'text-blue-500',    dot: 'bg-blue-500 animate-pulse' },
    completed: { icon: CheckCircle2, color: 'text-emerald-500', dot: 'bg-emerald-500' },
    failed:    { icon: XCircle,      color: 'text-rose-500',    dot: 'bg-rose-500' },
};

function formatDuration(startTime, endTime) {
    if (!startTime) return '';
    const end = endTime || Date.now() / 1000;
    const secs = Math.max(0, Math.round(end - startTime));
    if (secs < 60) return `${secs}s`;
    return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

/* ──────────────────────────────────────────────────────────────────
 * MarkdownRenderer (lightweight inline version)
 * ────────────────────────────────────────────────────────────────── */

const MarkdownRenderer = React.memo(({ text }) => {
    if (!text) return null;
    const normalized = String(text).replace(/\\n/g, '\n');
    const lines = normalized.split('\n');
    const elements = [];
    let elementKey = 0;
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        if (!line.trim()) { i++; elements.push(<div key={`md-${elementKey++}`} className="h-3" />); continue; }
        const h3 = line.match(/^###\s+(.+)/);
        const h2 = line.match(/^##\s+(.+)/);
        const h1 = line.match(/^#\s+(.+)/);
        if (h3) { elements.push(<h3 key={`md-${elementKey++}`} className="text-sm font-bold text-zinc-700 dark:text-zinc-200 mt-3 mb-1">{h3[1]}</h3>); i++; continue; }
        if (h2) { elements.push(<h2 key={`md-${elementKey++}`} className="text-base font-bold text-zinc-800 dark:text-zinc-100 mt-4 mb-2">{h2[1]}</h2>); i++; continue; }
        if (h1) { elements.push(<h1 key={`md-${elementKey++}`} className="text-lg font-bold text-zinc-800 dark:text-zinc-100 mt-4 mb-2">{h1[1]}</h1>); i++; continue; }
        const ul = line.match(/^[-*]\s+(.+)/);
        if (ul) {
            const items = [];
            while (i < lines.length && lines[i].match(/^[-*]\s+(.+)/)) {
                items.push(lines[i].replace(/^[-*]\s+/, ''));
                i++;
            }
            elements.push(
                <ul key={`md-${elementKey++}`} className="list-disc pl-5 space-y-1 my-2">
                    {items.map((item, idx) => <li key={idx} className="text-xs text-zinc-600 dark:text-zinc-400">{item}</li>)}
                </ul>
            );
            continue;
        }
        elements.push(<p key={`md-${elementKey++}`} className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed">{line}</p>);
        i++;
    }
    return <div>{elements}</div>;
});

/* ──────────────────────────────────────────────────────────────────
 * ProtocolCard (Phase 3.3)
 * ────────────────────────────────────────────────────────────────── */

const ProtocolCard = React.memo(({ direction, data, timestamp, isDark }) => {
    const [showMetadata, setShowMetadata] = useState(false);
    if (!data) return null;

    const isRequest = direction === 'request';
    const raw = isRequest ? data.request : data.response;
    const text = typeof raw === 'string' ? raw : (raw?.text || raw?.response || JSON.stringify(raw, null, 2));
    const metadata = data.metadata || {};
    const hasMetadata = Object.keys(metadata).length > 0;
    const state = data.state || data.task_state;
    const hasAuth = data.authorization;
    const hasNotif = data.notification;

    const icon = hasAuth ? <Shield size={14} className="text-amber-500" />
        : hasNotif ? <Bell size={14} className="text-purple-500" />
        : isRequest ? <ArrowRight size={14} className="text-blue-500" />
        : <ArrowLeft size={14} className="text-emerald-500" />;

    const label = hasAuth ? 'AUTH' : hasNotif ? 'NOTIF' : isRequest ? 'REQUEST' : 'RESPONSE';
    const bgClass = isRequest
        ? 'bg-blue-50/50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-900'
        : 'bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-900';
    const ts = timestamp ? new Date(timestamp * 1000).toLocaleTimeString('en-GB') : '';

    return (
        <div className={`rounded-xl border p-3 ${bgClass}`}>
            <div className="flex items-center gap-2 mb-2">
                {icon}
                <span className="text-[10px] font-black uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{label}</span>
                {ts && <span className="text-[10px] text-zinc-400 ml-auto font-mono">{ts}</span>}
                {state && (
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        state.includes('COMPLETED') ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                        : state.includes('FAILED') ? 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300'
                        : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'
                    }`}>
                        {state.replace('TASK_STATE_', '')}
                    </span>
                )}
            </div>
            {(() => {
                // Extract A2A-T headers from metadata keys (extension URIs)
                const headerKeys = Object.keys(metadata).filter(k => k.includes('tmforum.org') || k.includes('a2aproject'));
                const otherKeys = Object.keys(metadata).filter(k => !headerKeys.includes(k));
                const hasHeaders = headerKeys.length > 0;
                if (!hasHeaders) return null;
                return (
                    <div className="mb-2 rounded-lg bg-zinc-100/60 dark:bg-zinc-800/40 p-2">
                        <div className="text-[9px] font-black uppercase text-zinc-400 mb-1">Headers: A2A-Extensions</div>
                        <div className="flex flex-wrap gap-1">
                            {headerKeys.map((k, idx) => (
                                <span key={idx} className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300">
                                    {k.split('/').pop()}
                                </span>
                            ))}
                        </div>
                    </div>
                );
            })()}
            {text && (
                <div className="rounded-lg bg-white/60 dark:bg-zinc-900/40 p-2 max-h-48 overflow-y-auto custom-scrollbar">
                    <div className="text-[9px] font-black uppercase text-zinc-400 mb-1">Body</div>
                    <MarkdownRenderer text={text} />
                </div>
            )}
            {hasMetadata && (
                <div className="mt-2">
                    <button
                        onClick={() => setShowMetadata(!showMetadata)}
                        className="flex items-center gap-1 text-[10px] font-bold text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
                    >
                        {showMetadata ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        Metadata ({Object.keys(metadata).length})
                    </button>
                    {showMetadata && (
                        <div className="mt-1 rounded-lg bg-zinc-50 dark:bg-zinc-900/60 p-2 max-h-40 overflow-y-auto custom-scrollbar">
                            {Object.entries(metadata).map(([key, val], idx) => (
                                <div key={idx} className="mb-1">
                                    <span className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 break-all">{key}:</span>
                                    <div className="ml-2 mt-0.5">
                                        <MarkdownRenderer text={typeof val === 'string' ? val : JSON.stringify(val, null, 2)} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
});

/* ──────────────────────────────────────────────────────────────────
 * AgentInteraction (Phase 3.6 inner component)
 * ────────────────────────────────────────────────────────────────── */

const AgentInteraction = React.memo(({ interaction, isDark }) => {
    const agent = interaction.agent || 'Unknown';
    return (
        <div className="flex flex-col gap-2 pl-3 border-l-2 border-zinc-200 dark:border-zinc-700 ml-2">
            <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-blue-400 to-indigo-500 flex items-center justify-center shrink-0">
                    <Bot size={12} className="text-white" />
                </div>
                <span className="text-xs font-bold text-zinc-700 dark:text-zinc-200">{agent}</span>
            </div>
            {interaction.request && (
                <ProtocolCard direction="request" data={interaction} timestamp={interaction.timestamp} isDark={isDark} />
            )}
            {interaction.response && (
                <ProtocolCard direction="response" data={interaction} timestamp={interaction.timestamp} isDark={isDark} />
            )}
            {interaction.negotiations && interaction.negotiations.length > 0 && (
                <div className="ml-4 rounded-xl border border-amber-200 dark:border-amber-900 bg-amber-50/50 dark:bg-amber-950/20 p-2 space-y-2">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase text-amber-600 dark:text-amber-400">
                        <MessageSquare size={12} />
                        Negotiation ({interaction.negotiations.length} round{interaction.negotiations.length > 1 ? 's' : ''})
                    </div>
                    {interaction.negotiations.map((neg, idx) => (
                        <div key={idx} className="text-[10px] text-zinc-600 dark:text-zinc-400 pl-2 border-l border-amber-300 dark:border-amber-800">
                            <span className="font-bold uppercase">{neg.type.replace('negotiation_', '')}:</span>{' '}
                            {neg.data?.concern || neg.data?.clarification || neg.data?.reason || ''}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
});

/* ──────────────────────────────────────────────────────────────────
 * SelfLoopCard (Phase 3.4)
 * ────────────────────────────────────────────────────────────────── */

const SelfLoopCard = React.memo(({ step, isDark }) => (
    <div className="flex flex-col gap-2 pl-3 border-l-2 border-purple-300 dark:border-purple-700 ml-2">
        <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-gradient-to-br from-purple-400 to-pink-500 flex items-center justify-center shrink-0">
                <RotateCcw size={12} className="text-white" />
            </div>
            <span className="text-xs font-bold text-purple-600 dark:text-purple-400">Self-Loop (Local Processing)</span>
        </div>
        {step.output && (
            <div className="rounded-lg bg-purple-50/50 dark:bg-purple-950/20 border border-purple-200 dark:border-purple-900 p-2 max-h-32 overflow-y-auto custom-scrollbar">
                <MarkdownRenderer text={typeof step.output === 'string' ? step.output : JSON.stringify(step.output)} />
            </div>
        )}
        {step.status === 'running' && !step.output && (
            <div className="flex items-center gap-2 text-xs text-purple-500">
                <Loader size={12} className="animate-spin" />
                <span>Processing...</span>
            </div>
        )}
    </div>
));

/* ──────────────────────────────────────────────────────────────────
 * RouteDecisionCard (Phase 3.6 inner)
 * ────────────────────────────────────────────────────────────────── */

const RouteDecisionCard = React.memo(({ data }) => {
    if (!data) return null;
    return (
        <div className="flex items-center gap-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-900/40 p-2 ml-4">
            <GitBranch size={14} className="text-zinc-500" />
            <span className="text-[10px] font-bold text-zinc-600 dark:text-zinc-400">
                Route: <span className="text-zinc-800 dark:text-zinc-200">{data.step || ''}</span>
                <ChevronRight size={10} className="inline mx-1" />
                <span className="text-blue-600 dark:text-blue-400">{data.next || data.next_step || ''}</span>
            </span>
            {data.reason && <span className="text-[10px] text-zinc-400 ml-2">{data.reason}</span>}
        </div>
    );
});

/* ──────────────────────────────────────────────────────────────────
 * StepPhase (Phase 3.6 main container)
 * ────────────────────────────────────────────────────────────────── */

const StepPhase = React.memo(({ step, isDark }) => {
    const statusInfo = StepStatusMap[step.status] || StepStatusMap.pending;
    const StatusIcon = statusInfo.icon;
    const duration = formatDuration(step.startTime, step.endTime);

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <div className={`w-2.5 h-2.5 rounded-full ${statusInfo.dot} shrink-0`} />
                <StatusIcon size={14} className={statusInfo.color + (step.status === 'running' ? ' animate-spin' : '')} />
                <span className="text-xs font-bold text-zinc-800 dark:text-zinc-100">{step.name}</span>
                <span className={`text-[10px] font-bold uppercase ${statusInfo.color}`}>
                    [{step.status}]
                </span>
                {duration && <span className="text-[10px] text-zinc-400 ml-auto font-mono">{duration}</span>}
                {step.isSelfLoop && (
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-purple-100 text-purple-600 dark:bg-purple-900/40 dark:text-purple-300">
                        SELF-LOOP
                    </span>
                )}
            </div>
            <div className="ml-5 flex flex-col gap-2">
                {step.isSelfLoop ? (
                    <SelfLoopCard step={step} isDark={isDark} />
                ) : (
                    step.interactions.map((interaction, idx) => (
                        <AgentInteraction key={idx} interaction={interaction} isDark={isDark} />
                    ))
                )}
                {step.route && <RouteDecisionCard data={step.route} />}
                {step.output && (
                    <div className="ml-4 rounded-lg bg-zinc-50 dark:bg-zinc-900/40 border border-zinc-200 dark:border-zinc-700 p-2">
                        <div className="text-[9px] font-black uppercase text-zinc-400 mb-1">Output</div>
                        <div className="max-h-24 overflow-y-auto custom-scrollbar">
                            <MarkdownRenderer text={typeof step.output === 'string' ? step.output : (step.output?.output || JSON.stringify(step.output))} />
                        </div>
                    </div>
                )}
                {step.error && (
                    <div className="ml-4 rounded-lg bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900 p-2">
                        <span className="text-[10px] font-bold text-rose-600 dark:text-rose-400">
                            Error: {step.error.error || JSON.stringify(step.error)}
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
});

/* ──────────────────────────────────────────────────────────────────
 * WorkflowHeader (Phase 3.1 inner)
 * ────────────────────────────────────────────────────────────────── */

const WorkflowHeader = React.memo(({ events, steps, isRunning }) => {
    const startEvent = events.find(e => e.type === 'start');
    const completeEvent = events.find(e => e.type === 'complete');
    const errorEvent = events.find(e => e.type === 'error');
    const wfName = startEvent?.data?.workflow || '';
    const totalSteps = startEvent?.data?.steps || 0;
    const completedSteps = steps.filter(s => s.status === 'completed').length;
    const failedSteps = steps.filter(s => s.status === 'failed').length;
    const startTime = startEvent?.timestamp;
    const endTime = completeEvent?.timestamp || errorEvent?.timestamp;
    const duration = formatDuration(startTime, endTime);
    const overallStatus = errorEvent ? 'failed' : completeEvent ? 'completed' : isRunning ? 'running' : 'pending';
    const statusInfo = StepStatusMap[overallStatus] || StepStatusMap.pending;
    const StatusIcon = statusInfo.icon;

    return (
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-700 bg-gradient-to-r from-zinc-50 to-zinc-100 dark:from-zinc-800/50 dark:to-zinc-900/50 p-4 flex items-center gap-4">
            <StatusIcon size={20} className={statusInfo.color + (overallStatus === 'running' ? ' animate-spin' : '')} />
            <div className="flex-1 min-w-0">
                <div className="text-sm font-black text-zinc-800 dark:text-zinc-100 truncate">{wfName || 'Workflow Execution'}</div>
                <div className="flex items-center gap-3 mt-1">
                    <span className={`text-[10px] font-bold uppercase ${statusInfo.color}`}>
                        {overallStatus === 'running' ? 'Executing' : overallStatus === 'completed' ? 'Completed' : overallStatus === 'failed' ? 'Failed' : 'Pending'}
                    </span>
                    {totalSteps > 0 && (
                        <span className="text-[10px] text-zinc-400">
                            Steps {completedSteps}/{totalSteps}
                            {failedSteps > 0 && <span className="text-rose-500"> ({failedSteps} failed)</span>}
                        </span>
                    )}
                    {duration && <span className="text-[10px] text-zinc-400 font-mono">{duration}</span>}
                </div>
            </div>
            {totalSteps > 0 && (
                <div className="w-24 h-1.5 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden">
                    <div
                        className={`h-full rounded-full transition-all duration-500 ${
                            overallStatus === 'failed' ? 'bg-rose-500' : overallStatus === 'completed' ? 'bg-emerald-500' : 'bg-blue-500'
                        }`}
                        style={{ width: `${totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0}%` }}
                    />
                </div>
            )}
        </div>
    );
});

/* ──────────────────────────────────────────────────────────────────
 * FinalResultCard (Phase 3.5)
 * ────────────────────────────────────────────────────────────────── */

const FinalResultCard = React.memo(({ events, steps, isDark }) => {
    const completeEvent = events.find(e => e.type === 'complete');
    const errorEvent = events.find(e => e.type === 'error');
    if (!completeEvent && !errorEvent) return null;

    const isComplete = !!completeEvent;
    const data = completeEvent?.data || errorEvent?.data || {};
    const history = data.history || [];
    const stepOutputs = data.step_outputs || {};
    const startTime = events.find(e => e.type === 'start')?.timestamp;
    const endTime = completeEvent?.timestamp || errorEvent?.timestamp;
    const duration = formatDuration(startTime, endTime);

    return (
        <div className={`rounded-2xl border p-4 ${
            isComplete
                ? 'border-emerald-200 dark:border-emerald-900 bg-emerald-50/50 dark:bg-emerald-950/20'
                : 'border-rose-200 dark:border-rose-900 bg-rose-50/50 dark:bg-rose-950/20'
        }`}>
            <div className="flex items-center gap-2 mb-3">
                {isComplete ? <CheckCircle2 size={16} className="text-emerald-500" /> : <XCircle size={16} className="text-rose-500" />}
                <span className="text-sm font-black text-zinc-800 dark:text-zinc-100">
                    {isComplete ? 'Workflow Complete' : 'Workflow Failed'}
                </span>
                {duration && <span className="text-[10px] text-zinc-400 ml-auto font-mono">Total: {duration}</span>}
            </div>
            {Object.keys(stepOutputs).length > 0 && (
                <div className="space-y-2">
                    <div className="flex items-center gap-1 text-[10px] font-bold uppercase text-zinc-500 dark:text-zinc-400">
                        <FileText size={12} />
                        Step Outputs
                    </div>
                    {Object.entries(stepOutputs).map(([stepName, output], idx) => (
                        <div key={idx} className="rounded-lg bg-white/60 dark:bg-zinc-900/40 p-2">
                            <span className="text-[10px] font-bold text-zinc-600 dark:text-zinc-300">{stepName}:</span>
                            <div className="mt-1 max-h-24 overflow-y-auto custom-scrollbar">
                                <MarkdownRenderer text={typeof output === 'string' ? output : (output?.output || JSON.stringify(output))} />
                            </div>
                        </div>
                    ))}
                </div>
            )}
            {history.length > 0 && (
                <details className="mt-2">
                    <summary className="cursor-pointer text-[10px] font-bold text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300">
                        Execution History ({history.length} entries)
                    </summary>
                    <div className="mt-1 max-h-32 overflow-y-auto custom-scrollbar space-y-1">
                        {history.map((h, idx) => (
                            <div key={idx} className="text-[10px] text-zinc-500 dark:text-zinc-400 rounded px-2 py-0.5 bg-zinc-50 dark:bg-zinc-900/40">
                                {typeof h === 'string' ? h : JSON.stringify(h)}
                            </div>
                        ))}
                    </div>
                </details>
            )}
        </div>
    );
});

/* ──────────────────────────────────────────────────────────────────
 * ExecutionTimeline (Phase 3.1 main container)
 * ────────────────────────────────────────────────────────────────── */

const ExecutionTimeline = React.memo(({ events, isDark, isRunning }) => {
    const steps = useMemo(() => {
        const result = groupEventsByStep(events);
        if (result.length > 0) {
            console.log('[Timeline] steps:', result.map(s => ({ name: s.name, status: s.status, selfLoop: s.isSelfLoop, interactions: s.interactions.length })));
        }
        return result;
    }, [events]);

    if (events.length === 0) {
        return (
            <div className="h-full flex flex-col items-center justify-center opacity-[0.15] dark:opacity-[0.25] text-zinc-400">
                <Clock size={64} strokeWidth={1.5} />
                <p className="text-xl font-black mt-4 uppercase tracking-widest">Idle</p>
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-4">
            <WorkflowHeader events={events} steps={steps} isRunning={isRunning} />
            <div className="space-y-4">
                {steps.map((step, idx) => (
                    <StepPhase key={idx} step={step} isDark={isDark} />
                ))}
            </div>
            <FinalResultCard events={events} steps={steps} isDark={isDark} />
        </div>
    );
});

export default ExecutionTimeline;
