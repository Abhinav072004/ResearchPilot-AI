import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity as ActivityIcon, ArrowDownToLine, ArrowRight, ArrowUpRight, BookOpen, ChevronRight, CircleHelp, Compass, FileText, FlaskConical, FolderOpen, Layers3, LibraryBig, LogOut, Menu, MessageSquare, Plus, Search, Settings, X } from 'lucide-react';
import { api, json, safeUrl } from './api';
import type { Account, Activity, Comparison, DocumentStructure, Evidence, Job, Named, Observation, Source, TableCell, Team } from './api';
import { EmptyProject, ResearchComposer, ResearchExamples, ResearchWelcome } from './research';
import '@fontsource-variable/dm-sans';
import '@fontsource/instrument-serif/400.css';
import '@fontsource/instrument-serif/400-italic.css';
import './style.css';

type View = 'Research' | 'Literature' | 'Library' | 'Data explorer' | 'Reports' | 'Activity' | 'Settings';
const views = [
  { name: 'Research', icon: FlaskConical }, { name: 'Literature', icon: Search },
  { name: 'Library', icon: LibraryBig }, { name: 'Data explorer', icon: Layers3 },
  { name: 'Reports', icon: FileText }, { name: 'Activity', icon: ActivityIcon },
] as const;

function Brand() {
  return <span className="brand"><span className="brand-mark"><Compass size={20} strokeWidth={1.9}/></span><span>ResearchPilot <span className="brand-ai">AI</span></span></span>;
}

function Login({onAccount}: {onAccount: (account: Account) => void}) {
  const [register, setRegister] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError('');
    try {
      onAccount(await api<Account>(register ? '/auth/register' : '/auth/login',
        json({email: data.get('email'), password: data.get('password')})));
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  return <main className="auth">
    <div className="auth-main">
      <header className="auth-nav"><Brand/><a href="https://github.com/Abhinav072004/ResearchPilot-AI"
        target="_blank" rel="noreferrer">Source code <ArrowUpRight size={15}/></a></header>
      <div className="auth-inner">
        <div className="auth-copy">
          <h1>{register ? 'Create your account' : 'Welcome back'}</h1>
          <p>{register ? 'Set up your workspace to organize papers, questions, and reports.' : 'Sign in to your research workspace.'}</p>
        </div>
        <form onSubmit={submit} className="auth-form">
          <label>Email<input type="email" name="email" placeholder="you@university.edu" autoComplete="email" required/></label>
          <label>Password<input name="password" type="password" minLength={12} maxLength={128}
            placeholder={register ? 'At least 12 characters' : 'Your password'}
            autoComplete={register ? 'new-password' : 'current-password'} required/></label>
          {error && <p role="alert" className="error">{error}</p>}
          <button className="primary auth-submit" disabled={busy}>
            {register ? 'Create account' : 'Sign in'} <ArrowRight size={17}/>
          </button>
          <div className="auth-switch">
            <span>{register ? 'Already have an account?' : 'New to ResearchPilot?'}</span>
            <button type="button" className="text-button" onClick={() => { setRegister(!register); setError(''); }}>
              {register ? 'Sign in instead' : 'Create an account'}
            </button>
          </div>
        </form>
      </div>
    </div>
    <section className="auth-hero" aria-label="About ResearchPilot">
      <div className="auth-hero-copy">
        <h2>Follow <em>the evidence.</em></h2>
        <p>Ask questions about scientific literature, inspect the original passages, and export your findings with citations.</p>
      </div>
    </section>
  </main>;
}

function SourceList({rows, onDoi}: {rows: Source[]; onDoi: (doi: string) => void}) {
  return <div className="stack">{rows.map(row => <article className="card record" key={row.external_id}>
    <div><h3>{row.title}</h3><p>{[row.authors.filter(Boolean).join(', '), row.journal, row.year].filter(Boolean).join(' · ')}</p>
      <span className="status">{row.retracted ? 'Retracted' : row.access.replaceAll('_', ' ')}</span></div>
    <div className="actions">{row.doi && <button type="button" onClick={() => onDoi(row.doi!)}>Verify DOI</button>}
      {safeUrl(row.url) && <a href={safeUrl(row.url)} target="_blank" rel="noreferrer">Source <ArrowUpRight size={15}/></a>}</div>
  </article>)}</div>;
}

function StructuredTable({cells, caption}: {cells: TableCell[]; caption?: string}) {
  const rows = new Map<number, TableCell[]>();
  cells.forEach(cell => {
    const row = rows.get(cell.row) ?? [];
    row.push(cell);
    rows.set(cell.row, row);
  });
  return <div className="scroll"><table>{caption && <caption>{caption}</caption>}<tbody>
    {[...rows.entries()].sort(([a], [b]) => a - b).map(([row, columns]) => <tr key={row}>
      {[...columns].sort((a, b) => a.column - b.column).map(cell => {
        const Tag = cell.header ? 'th' : 'td';
        return <Tag key={cell.column} rowSpan={cell.rowspan} colSpan={cell.colspan}>{cell.text}</Tag>;
      })}
    </tr>)}
  </tbody></table></div>;
}

function ResultsTable({rows, inspect}: {rows: Observation[]; inspect: (id: string) => void}) {
  if (!rows.length) return <p className="muted">No observations available.</p>;
  return <div className="scroll"><table><thead><tr><th>Paper</th><th>Metric</th><th>Value</th><th>Study</th><th>Conditions</th><th>Evidence</th></tr></thead>
    <tbody>{rows.map(row => <tr key={row.id}>
      <td>{row.title}</td><td>{row.metric}</td><td>{row.value} {row.unit}</td><td>{row.study_type}</td>
      <td>{Object.entries(row.conditions).map(([key, value]) => key.replaceAll('_', ' ') + ' ' + value).join(' · ') || 'Unavailable'}</td>
      <td><button className="text-button" onClick={() => inspect(row.passage_id)}>View passage</button></td>
    </tr>)}</tbody></table></div>;
}

function Workspace({account, onLogout}: {account: Account; onLogout: () => void}) {
  const [view, setView] = useState<View>('Research');
  const [projects, setProjects] = useState<Named[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [project, setProject] = useState('');
  const [projectForm, setProjectForm] = useState(false);
  const [menu, setMenu] = useState(false);
  const [query, setQuery] = useState('');
  const [discover, setDiscover] = useState(false);
  const [job, setJob] = useState<Job>();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [searched, setSearched] = useState(false);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [lastSearch, setLastSearch] = useState({q: '', provider: 'crossref'});
  const [papers, setPapers] = useState<Named[]>([]);
  const [passages, setPassages] = useState<Evidence[]>([]);
  const [structure, setStructure] = useState<DocumentStructure>();
  const [team, setTeam] = useState<Team>();
  const [observations, setObservations] = useState<Observation[]>([]);
  const [comparison, setComparison] = useState<Comparison>();
  const [selected, setSelected] = useState<Evidence>();
  const closeEvidence = useRef<HTMLButtonElement>(null);
  const evidenceTrigger = useRef<HTMLElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [conversation, setConversation] = useState('');
  const [conversations, setConversations] = useState<Named[]>([]);
  const [usage, setUsage] = useState<{model: string; tracked_calls: number; input_tokens: number;
    output_tokens: number; estimated_cost: number | null; priced_calls: number}[]>([]);
  const [messages, setMessages] = useState<{id: string; body: string}[]>([]);
  const scope = '/projects/' + project;
  const activeProject = projects.find(p => p.id === project);
  const activeResearch = job?.kind === 'research' ? job : undefined;
  const researchBusy = ['queued', 'running', 'awaiting_approval'].includes(activeResearch?.status ?? '');
  const recentResearch = jobs.filter(row => row.kind === 'research').slice(0, 5);
  const earlierMessages = activeResearch?.title && messages.at(-1)?.body === activeResearch.title
    ? messages.slice(0, -1) : messages;

  async function run(work: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try { await work(); } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    let active = true;
    api<Named[]>('/projects').then(rows => {
      if (active) { setProjects(rows); setProject(rows[0]?.id ?? ''); }
    }).catch(err => { if (active) setError(err.message); }).finally(() => {
      if (active) setProjectsLoading(false);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!project) return;
    let active = true;
    const load = async () => {
      if (view === 'Library') {
        const rows = await api<Named[]>(scope + '/papers');
        if (active) setPapers(rows);
      } else if (view === 'Data explorer') {
        const rows = await api<Observation[]>(scope + '/observations');
        if (active) setObservations(rows);
      } else if (view === 'Reports' || view === 'Activity') {
        const rows = await api<Job[]>(scope + '/jobs');
        if (active) setJobs(rows);
      } else if (view === 'Settings') {
        const [rows, members] = await Promise.all([api<typeof usage>(scope + '/usage'), api<Team>(scope + '/team')]);
        if (active) { setUsage(rows); setTeam(members); }
      } else if (view === 'Research') {
        const [rows, history] = await Promise.all([
          api<Named[]>(scope + '/conversations'), api<Job[]>(scope + '/jobs'),
        ]);
        if (active) { setConversations(rows); setJobs(history); }
      }
    };
    load().catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [project, scope, view, job?.status]);

  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return;
    let active = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const stream = new EventSource('/api/v1/jobs/' + job.id + '/events');
    stream.onmessage = event => { if (active) setJob(JSON.parse(event.data)); };
    async function poll() {
      try {
        const current = await api<Job>('/jobs/' + job!.id);
        if (!active) return;
        setJob(current);
        if (['queued', 'running'].includes(current.status)) retry = setTimeout(poll, 2000);
      } catch (err) {
        if (active) setError((err as Error).message);
      }
    }
    stream.onerror = () => { stream.close(); if (active) void poll(); };
    return () => { active = false; stream.close(); if (retry) clearTimeout(retry); };
  }, [job?.id, job?.status]);

  useEffect(() => {
    if (!selected) return;
    closeEvidence.current?.focus();
    const trigger = evidenceTrigger.current;
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, [selected?.id]);

  function switchProject(id: string) {
    setProject(id); setJob(undefined); setSelected(undefined); setPassages([]); setStructure(undefined); setTeam(undefined);
    setComparison(undefined); setActivity([]); setJobs([]); setPapers([]); setObservations([]);
    setConversation(''); setConversations([]); setMessages([]); setUsage([]); setNotice(''); setError('');
    setQuery(''); setDiscover(false);
  }

  function navigate(to: View) {
    setView(to); setMenu(false); setNotice(''); setError('');
  }

  function newProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    void run(async () => {
      await createProject(String(data.get('title')));
      if (!project) {
        setQuery(query);
        setDiscover(discover);
      }
      setProjectForm(false);
    });
  }

  async function createProject(title: string) {
    const entry = await api<Named>('/projects', json({title}));
    setProjects(items => [...items, entry]);
    switchProject(entry.id);
    return entry.id;
  }

  function focusComposer() {
    requestAnimationFrame(() => document.getElementById('question')?.focus());
  }

  function newQuestion() {
    navigate('Research');
    setJob(undefined); setConversation(''); setMessages([]); setQuery(''); setDiscover(false);
    setSelected(undefined);
    focusComposer();
  }

  function startResearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = query.trim();
    if (question.length < 2 || researchBusy) return;
    const data = new FormData(event.currentTarget);
    void run(async () => {
      let id = project;
      if (!id) {
        id = await createProject(question.slice(0, 80));
        setQuery(question);
        setDiscover(data.has('discover'));
      }
      const root = '/projects/' + id;
      let thread = conversation;
      if (!thread) {
        const item = await api<Named>(root + '/conversations', json({title: question.slice(0, 100)}));
        setConversations(rows => rows.some(row => row.id === item.id) ? rows : [item, ...rows]);
        setConversation(item.id);
        thread = item.id;
      }
      const entry = await api<Job>(root + '/research', json({
        query: question, conversation_id: thread, record_message: true, domain: data.get('domain') || 'auto',
        discover: data.has('discover'), external_model: data.has('model') || data.has('synthesis'),
        synthesize: data.has('synthesis'),
      }));
      setMessages(rows => [...rows, {id: entry.id, body: question}]);
      setJob(entry); setQuery('');
      setJobs(rows => [entry, ...rows.filter(row => row.id !== entry.id)]);
    });
  }

  function searchLit(q: string, provider: string, offset: number) {
    void run(async () => {
      const params = new URLSearchParams({q, provider, offset: String(offset)});
      const result = await api<{records: Source[]; next_offset: number | null}>('/literature/search?' + params);
      setSources(rows => offset ? [...rows, ...result.records] : result.records);
      setLastSearch({q, provider}); setSearched(true); setNextOffset(result.next_offset);
    });
  }

  function verify(doi: string) {
    void run(async () => {
      const row = await api<Source>('/literature/doi?doi=' + encodeURIComponent(doi));
      setNotice(`DOI resolved: ${row.title} · ${row.doi}${row.retracted ? ' · Retracted' : ''}`);
    });
  }

  function inspect(id: string) {
    evidenceTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    void run(async () => setSelected(await api<Evidence>('/evidence/' + id)));
  }

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (!data.get('doi')) data.delete('doi');
    void run(async () => {
      setJob(await api<Job>(scope + '/papers', {method: 'POST', body: data}));
      form.reset();
    });
  }

  function showRun(id: string, destination?: View) {
    void run(async () => {
      const [entry, events] = await Promise.all([api<Job>('/jobs/' + id), api<Activity[]>('/jobs/' + id + '/timeline')]);
      setJob(entry); setActivity(events);
      const nextView = destination ?? (entry.kind === 'research' && view === 'Reports' ? 'Research' : view);
      navigate(nextView);
      if (entry.kind === 'research' && nextView === 'Research') {
        const thread = entry.conversation_id || '';
        setConversation(thread);
        setMessages([]);
        if (thread) {
          const detail = await api<{messages: typeof messages}>('/conversations/' + thread).catch(() => null);
          if (detail) {
            const position = detail.messages.map(message => message.body).lastIndexOf(entry.title || '');
            setMessages(position >= 0 ? detail.messages.slice(0, position + 1) : []);
          }
        }
      }
    });
  }

  function createReport() {
    void run(async () => {
      setJob(await api<Job>(scope + '/reports', json({research_id: job?.id, title: 'Research report'})));
      navigate('Reports');
    });
  }

  function panel(body: ReactNode) {
    return <section className="card">{body}</section>;
  }

  const headings: Record<View, [string, string]> = {
    Research: ['Research workspace', 'Ask a question and inspect the evidence from your project library.'],
    Literature: ['Scholarly literature', 'Search academic indexes and resolve publication identifiers.'],
    Library: ['Project library', 'Upload permitted papers and inspect their extracted passages.'],
    'Data explorer': ['Experimental data', 'Review source-linked observations and compare matching conditions.'],
    Reports: ['Report studio', 'Download completed reports and return to saved research runs.'],
    Activity: ['Workflow activity', 'Inspect processing status and agent events.'],
    Settings: ['Account settings', 'Manage your current session.'],
  };

  return <div className="shell">
    {menu && <button className="sidebar-scrim" aria-label="Close menu" onClick={() => setMenu(false)}/>}
    <aside id="workspace-sidebar" className={menu ? 'sidebar open' : 'sidebar'}>
      <Brand/>
      <button className="new-question" onClick={newQuestion} disabled={busy}><Plus size={18}/> New question</button>
      <div className="side-group"><div className="side-label">Workspace</div>
        {views.map(({name, icon: Icon}) => <button key={name} className={view === name ? 'nav active' : 'nav'}
          aria-current={view === name ? 'page' : undefined} onClick={() => navigate(name)}><Icon size={17}/>{name}</button>)}
      </div>
      <div className="side-group"><div className="side-label row">Projects <button className="icon" aria-label="New project"
        onClick={() => { navigate('Research'); setProjectForm(true); }}><Plus size={17}/></button></div>
        {projects.map(row => <button key={row.id} className={row.id === project ? 'nav active' : 'nav'}
          disabled={busy} onClick={() => { switchProject(row.id); navigate('Research'); }}><FolderOpen size={17}/>{row.title}</button>)}
      </div>
      {!!recentResearch.length && <div className="side-group"><div className="side-label">Recent research</div>
        {recentResearch.map(item => <button key={item.id} className={activeResearch?.id === item.id ? 'nav recent-item active' : 'nav recent-item'}
          title={item.title || 'Research results'} disabled={busy} onClick={() => showRun(item.id, 'Research')}>
          <MessageSquare size={16}/><span>{item.title || 'Research results'}</span>
        </button>)}
      </div>}
      <div className="side-bottom">
        <button className="nav" onClick={() => navigate('Settings')}><Settings size={17}/> Settings</button>
        <div className="account-strip"><span className="account-avatar" aria-hidden="true">{account.email.slice(0, 2).toUpperCase()}</span>
          <span title={account.email}>{account.email}</span></div>
      </div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <button className="icon menu" aria-label="Toggle menu" aria-expanded={menu} aria-controls="workspace-sidebar"
          onClick={() => setMenu(!menu)}><Menu size={21}/></button>
        <div className="breadcrumb"><span>{activeProject?.title ?? 'Workspace'}</span><ChevronRight size={14}/><strong>{view}</strong></div>
        {view === 'Research' && project && <button className="topbar-action" onClick={() => navigate('Library')}>
          <LibraryBig size={17}/> <span>Project library</span></button>}
      </header>
      <main className={view === 'Research' ? 'content research-content' : 'content'}>
        {view !== 'Research' && <header className="page-heading"><h1>{headings[view][0]}</h1><p>{headings[view][1]}</p></header>}
        {error && <p role="alert" className="error">{error}</p>}
        {notice && <p role="status" className="notice">{notice}</p>}
        {projectForm && panel(<form className="inline" onSubmit={newProject}>
          <label>Project title<input name="title" required maxLength={150} autoFocus/></label>
          <button className="primary" disabled={busy}>Create project</button>
          <button type="button" onClick={() => setProjectForm(false)}>Cancel</button>
        </form>)}
        {!project && view !== 'Literature' && view !== 'Settings' && view !== 'Research' && !projectForm &&
          <EmptyProject onCreate={() => setProjectForm(true)}/>}
        {view === 'Research' && <>
          {!activeResearch && !messages.length && <ResearchWelcome/>}
          {!activeResearch && messages.length > 0 && <div className="conversation-space">
            {messages.map(message => <p className="history" key={message.id}>{message.body}</p>)}
          </div>}
          {activeResearch && <>
            <h1 className="sr-only">Research workspace</h1>
            <div className="conversation-space">
              {earlierMessages.map(message => <p className="history" key={message.id}>{message.body}</p>)}
              {activeResearch.title && <p className="history current-question">{activeResearch.title}</p>}
            </div>
          </>}
          {job?.kind === 'research' && <section className="research-answer stack">
            <div className="answer-heading"><span className="answer-mark"><Compass size={19}/></span>
              <h2>Research results</h2>
              <span className={researchBusy ? 'status working' : 'status'} role="status">
                {job.status === 'running' ? 'Researching' : job.status.replaceAll('_', ' ')}
              </span></div>
            {researchBusy && job.status !== 'awaiting_approval' && !job.result?.claims?.length &&
              <p className="researching"><span className="spinner" aria-hidden="true"/>
                {job.status === 'queued' ? 'Waiting for a research worker' : 'Looking for supporting evidence'}</p>}
            {job.error && <p className="error" role="alert">{job.error}</p>}
            {job.status === 'awaiting_approval' && panel(<><p>{job.result?.approval?.purpose}</p><div className="actions">
              {[true, false].map(approved => <button key={String(approved)} disabled={busy} onClick={() => void run(async () =>
                setJob(await api<Job>('/jobs/' + job.id + '/approval', json({approved}))))}>{approved ? 'Approve' : 'Decline'}</button>)}</div></>)}
            {job.result?.imported_papers?.length ? <p className="notice">Full text ready for {job.result.imported_papers.length}
              {job.result.imported_papers.length === 1 ? ' paper.' : ' papers.'}</p> : null}
            {job.result?.claims?.map((claim, index) => <article key={claim.claim_id} className="card evidence-card">
              {claim.type === 'model_checked_synthesis' && <h3>Model-checked synthesis</h3>}
              <blockquote>{claim.text}</blockquote>
              {(claim.supporting_evidence ?? [claim.evidence]).map((source, sourceIndex) =>
                <button key={source.id + sourceIndex} className="text-button" onClick={() => inspect(source.id)}>
                  <BookOpen size={15}/> [{index + 1}{claim.supporting_evidence ? '.' + (sourceIndex + 1) : ''}] {source.title} · {source.section}</button>)}
            </article>)}
            {job.result?.gaps?.map(gap => <p key={gap} className="notice"><CircleHelp size={16}/> {gap}</p>)}
            {Object.entries(job.result?.comparisons ?? {}).map(([metric, result]) => <article key={metric} className="card">
              <h3>{metric}</h3><p className="muted">{result.interpretation}</p>
              {result.matched.map((group, i) => <ResultsTable key={i} rows={group.rows} inspect={inspect}/>)}
              {!result.matched.length && <p className="muted">No comparable observations found.</p>}
            </article>)}
            {job.result?.metadata_leads?.length ? <><h3>Verified metadata leads</h3><SourceList rows={job.result.metadata_leads} onDoi={verify}/></> : null}
            {job.status === 'succeeded' && <div className="actions"><button className="primary" disabled={busy} onClick={createReport}>Generate report <ArrowRight size={16}/></button>
              <button onClick={() => showRun(job.id, 'Activity')}><ActivityIcon size={16}/> View activity</button></div>}
          </section>}
          <div className={activeResearch ? 'composer-dock' : 'composer-start'}>
            <ResearchComposer query={query} onQuery={setQuery} discover={discover} onDiscover={setDiscover}
              busy={busy || researchBusy || projectsLoading} onSubmit={startResearch} onSources={() => navigate('Library')}/>
            {project && conversations.length > 0 && <label className="conversation-picker">
              <MessageSquare size={14}/><span>Conversation</span><select value={conversation} onChange={event => {
                const id = event.target.value;
                setConversation(id); setMessages([]); setJob(undefined);
                const lastRun = id && jobs.find(item => item.kind === 'research' && item.conversation_id === id);
                if (lastRun) showRun(lastRun.id, 'Research');
                else if (id) void run(async () => setMessages((await api<{messages: typeof messages}>('/conversations/' + id)).messages));
              }}><option value="">New conversation</option>{conversations.map(row =>
                <option key={row.id} value={row.id}>{row.title}</option>)}</select>
            </label>}
          </div>
          {!activeResearch && !messages.length && <>
            <ResearchExamples onExample={example => { setQuery(example.question); setDiscover(example.discover); focusComposer(); }}/>
            {!projectsLoading && !project && !projectForm && <button className="text-button create-project-link"
              onClick={() => setProjectForm(true)}><FolderOpen size={16}/> New project</button>}
          </>}
        </>}
        {view === 'Literature' && <>
          {panel(<form className="inline" onSubmit={event => {
            event.preventDefault(); const data = new FormData(event.currentTarget);
            searchLit(String(data.get('q')), String(data.get('provider')), 0);
          }}>
            <label className="grow">Search term<input name="q" minLength={2} maxLength={300} required placeholder="Title, author, or scientific topic"/></label>
            <label>Index<select name="provider">{['crossref','openalex','semantic_scholar','arxiv','pubmed','europe_pmc','core'].map(p =>
              <option key={p} value={p}>{p.replaceAll('_', ' ')}</option>)}</select></label>
            <button className="primary" disabled={busy}><Search size={16}/> Search</button>
          </form>)}
          <form className="inline compact" onSubmit={event => {
            event.preventDefault(); verify(String(new FormData(event.currentTarget).get('doi')));
          }}><label>Resolve DOI<input name="doi" required placeholder="10.…"/></label><button disabled={busy}>Verify</button></form>
          {searched && !sources.length && <p className="muted">No records found.</p>}
          <SourceList rows={sources} onDoi={verify}/>
          {nextOffset !== null && <button disabled={busy} onClick={() => searchLit(lastSearch.q, lastSearch.provider, nextOffset)}>Load more</button>}
        </>}
        {view === 'Library' && project && <>
          {panel(<form className="inline" onSubmit={event => {
            event.preventDefault();
            const form = event.currentTarget;
            const doi = String(new FormData(form).get('doi'));
            void run(async () => {
              setJob(await api<Job>(scope + '/papers/import', json({doi})));
              form.reset();
            });
          }}>
            <label className="grow">DOI for licensed full text<input name="doi" required maxLength={330} placeholder="10.…"/></label>
            <button className="primary" disabled={busy}>Import licensed full text</button>
          </form>)}
          {panel(<form className="stack" onSubmit={upload}>
            <div className="inline"><label className="grow">Paper title<input name="title" required maxLength={150}/></label>
              <label>Associated DOI (optional)<input name="doi" maxLength={330}/></label></div>
            <label>Paper file<input name="file" type="file" accept=".pdf,.xml,application/pdf,application/xml" required/></label>
            <label className="check"><input name="permitted" type="checkbox" value="true" required/> I have permission to process this paper</label>
            <div><button className="primary" disabled={busy}>Upload paper <ArrowRight size={16}/></button></div>
          </form>)}
          {job?.kind === 'ingest' && <p className="notice" role="status">Ingestion {job.status}{job.error && ' · ' + job.error}</p>}
          {papers.length === 0 && <p className="muted">Your project library is empty.</p>}
          {papers.map(paper => <div className="actions" key={paper.id}>
            <button onClick={() => void run(async () => {
              const root = scope + '/papers/' + paper.id;
              const [text, details] = await Promise.all([api<Evidence[]>(root + '/passages'), api<DocumentStructure>(root + '/structure')]);
              setPassages(text); setStructure(details);
            })}><BookOpen size={16}/>{paper.title}</button>
            <a href={'/api/v1' + scope + '/papers/' + paper.id + '/original'}><ArrowDownToLine size={14}/> Original</a>
          </div>)}
          {structure?.bibliography.abstract && <article className="card"><h3>Abstract</h3>
            <p>{structure.bibliography.abstract}</p></article>}
          {structure?.artifacts.map(entry => <article className="card" key={entry.id}>
            <h3>{entry.data.label || entry.kind.replaceAll('_', ' ')}{entry.page ? ' · p. ' + entry.page : ''}</h3>
            {entry.data.cells ? <StructuredTable cells={entry.data.cells} caption={entry.data.caption}/> : <p>{entry.data.text}</p>}
            <button className="text-button" onClick={() => inspect(entry.passage_id)}>Inspect evidence</button>
          </article>)}
          {passages.map(entry => <article className="card" key={entry.id}><h3>{entry.section}{entry.page ? ' · p. ' + entry.page : ''}</h3>
            <p>{entry.text}</p><button className="text-button" onClick={() => inspect(entry.id)}>Inspect evidence</button></article>)}
        </>}
        {view === 'Data explorer' && project && <>
          {panel(<form className="inline" onSubmit={event => {
            event.preventDefault(); const data = new FormData(event.currentTarget);
            void run(async () => setComparison(await api<Comparison>(scope + '/compare', json({metric: data.get('metric')}))));
          }}><label>Metric<input name="metric" required placeholder="hydrogen yield"/></label><button className="primary" disabled={busy}>Compare papers</button></form>)}
          {comparison ? <>
            <p className="notice">{comparison.interpretation}</p>
            {comparison.matched.map((group, index) => <section key={index} className="card">
              <h3>Observed span {group.observed_span} {group.unit}</h3><ResultsTable rows={group.rows} inspect={inspect}/>
            </section>)}
            <h3>Unmatched observations</h3><ResultsTable rows={comparison.unmatched} inspect={inspect}/>
          </> : <ResultsTable rows={observations} inspect={inspect}/>}
        </>}
        {(view === 'Activity' || view === 'Reports') && project && <>
          {view === 'Reports' && job?.kind === 'report' && <p role="status" className="notice">Report {job.status}{job.error && ' · ' + job.error}</p>}
          {jobs.filter(entry => view === 'Activity' || entry.kind !== 'ingest').map(entry => <article className="card record" key={entry.id}>
            <div><h3>{entry.title || entry.kind}</h3><span className="status">{entry.status.replaceAll('_', ' ')}</span></div><div className="actions">
              {view === 'Reports' && entry.kind === 'report' && entry.status === 'succeeded' ?
                <>
                  {['markdown', 'docx', 'pdf'].map(format => <a key={format} href={`/api/v1/reports/${entry.id}/export?format=${format}`}><ArrowDownToLine size={14}/>{format.toUpperCase()}</a>)}
                  {['apa', 'ieee'].map(style => <a key={style} href={`/api/v1/reports/${entry.id}/references?style=${style}`}>{style.toUpperCase()}</a>)}
                </>
              : <button onClick={() => showRun(entry.id)}>Open run</button>}</div></article>)}
          {!jobs.length && <p className="muted">No runs in this project.</p>}
          {view === 'Activity' && activity.length > 0 && panel(<ol className="timeline">{activity.map((entry, index) =>
            <li key={index}>{entry.stage.replaceAll('_', ' ')} <time>{new Date(entry.created * 1000).toLocaleTimeString()}</time></li>)}</ol>)}
        </>}
        {view === 'Settings' && project && panel(<>
          <h2>Project model usage</h2>
          {usage.length ? <div className="scroll"><table>
            <thead><tr><th>Model</th><th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Estimated cost (USD)</th></tr></thead>
            <tbody>{usage.map(row => <tr key={row.model}><td>{row.model}</td><td>{row.tracked_calls}</td>
              <td>{row.input_tokens}</td><td>{row.output_tokens}</td>
              <td>{row.estimated_cost === null ? 'Unavailable' : row.estimated_cost.toFixed(6)}
                {row.priced_calls < row.tracked_calls && row.estimated_cost !== null ? ' (partial)' : ''}</td></tr>)}</tbody>
          </table></div> : <p className="muted">This project has no recorded model calls.</p>}
        </>)}
        {view === 'Settings' && project && team?.role === 'owner' && panel(<>
          <h2>Workspace access</h2>
          <p>Workspace roles apply to all projects in this workspace.</p>
          <form className="inline" onSubmit={event => {
            event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
            void run(async () => {
              await api(scope + '/team', json({email: values.get('email'), role: values.get('role')}));
              setTeam(await api<Team>(scope + '/team')); form.reset();
            });
          }}>
            <label>Registered email<input type="email" name="email" required/></label>
            <label>Role<select name="role"><option value="viewer">Viewer</option><option value="editor">Editor</option></select></label>
            <button disabled={busy}>Grant access</button>
          </form>
          {team.members.map(member => <div className="row" key={member.id}>
            <span>{member.email}</span>{member.role === 'owner' ? <span>Owner</span> : <div className="actions">
              <select aria-label={'Role for ' + member.email} value={member.role} disabled={busy} onChange={event => {
                const role = event.target.value;
                void run(async () => {
                  await api(scope + '/team/' + member.id, json({role}, 'PATCH'));
                  setTeam(await api<Team>(scope + '/team'));
                });
              }}><option value="viewer">Viewer</option><option value="editor">Editor</option></select>
              <button disabled={busy} onClick={() => void run(async () => {
                await api(scope + '/team/' + member.id, {method: 'DELETE'});
                setTeam(await api<Team>(scope + '/team'));
              })}>Revoke access</button>
            </div>}
          </div>)}
        </>)}
        {view === 'Settings' && activeProject && team?.role !== 'viewer' && panel(<>
          <h2>Project settings</h2>
          <form className="inline" key={project} onSubmit={event => {
            event.preventDefault(); const title = new FormData(event.currentTarget).get('title');
            void run(async () => {
              const changed = await api<Named>(scope, json({title}, 'PATCH'));
              setProjects(rows => rows.map(row => row.id === changed.id ? changed : row));
              setNotice('Project renamed.');
            });
          }}><label>Project title<input name="title" defaultValue={activeProject.title} required maxLength={150}/></label>
            <button disabled={busy}>Save title</button></form>
          {team?.role === 'owner' && <button className="delete-button" disabled={busy} onClick={() => {
            if (!window.confirm('Delete this project, its source files, and all reports?')) return;
            void run(async () => {
              await api(scope, {method: 'DELETE'});
              const remaining = projects.filter(row => row.id !== project);
              setProjects(remaining); switchProject(remaining[0]?.id ?? '');
              setNotice('Project deletion scheduled.');
            });
          }}>Delete project</button>}
        </>)}
        {view === 'Settings' && panel(<><h2>{account.email}</h2><button onClick={() => void run(async () => {
          await api('/auth/logout', {method: 'POST'}); onLogout();
        })}><LogOut size={16}/> Sign out</button></>)}
      </main>
    </div>
    {selected && <aside className="inspector" aria-label="Evidence inspector" onKeyDown={event => {
      if (event.key === 'Escape') setSelected(undefined);
    }}>
      <div className="row"><h2>Evidence inspector</h2><button ref={closeEvidence} className="icon" aria-label="Close evidence" onClick={() => setSelected(undefined)}><X size={20}/></button></div>
      <h3>{selected.title}</h3>
      <p className="muted">{[selected.metadata.authors?.join(', '), selected.metadata.year, selected.metadata.journal].filter(Boolean).join(' · ')}</p>
      <p className="muted">{[selected.section, selected.page ? 'p. ' + selected.page : selected.anchor.xml_path, selected.access.replaceAll('_', ' ')].filter(Boolean).join(' · ')}</p>
      {selected.doi && <div><a href={safeUrl('https://doi.org/' + selected.doi)} target="_blank" rel="noreferrer">{selected.doi} <ArrowUpRight size={14}/></a>
        {selected.metadata.document_link === 'user_asserted' && <p className="muted">DOI association supplied by the uploader.</p>}</div>}
      {safeUrl(selected.metadata.source_url ?? null) && <a href={safeUrl(selected.metadata.source_url ?? null)}
        target="_blank" rel="noreferrer">Published full text <ArrowUpRight size={14}/></a>}
      {safeUrl(selected.metadata.licence ?? null) && <p><a href={safeUrl(selected.metadata.licence ?? null)}
        target="_blank" rel="noreferrer">Reuse licence <ArrowUpRight size={14}/></a></p>}
      {selected.anchor.extractor === 'tesseract' && <p className="muted">OCR transcription
        {typeof selected.anchor.ocr_confidence === 'number' ? ' · ' + selected.anchor.ocr_confidence.toFixed(1) + '% word confidence' : ''}</p>}
      <blockquote>{selected.text}</blockquote>
    </aside>}
  </div>;
}

function App() {
  const [account, setAccount] = useState<Account | null>();
  useEffect(() => { api<Account>('/auth/me').then(setAccount).catch(() => setAccount(null)); }, []);
  if (account === undefined) return <main className="loading-shell" aria-busy="true"><Brand/></main>;
  return account ? <Workspace account={account} onLogout={() => setAccount(null)}/> : <Login onAccount={setAccount}/>;
}

createRoot(document.getElementById('root')!).render(<App/>);
