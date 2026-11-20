import { useRef } from 'react';
import type { FormEvent } from 'react';
import {
  ArrowUp, ArrowUpRight, Compass, FilePlus2, FileSearch, GitCompareArrows,
  Globe2, Plus, SlidersHorizontal,
} from 'lucide-react';

const domains = [
  ['auto', 'All disciplines'], ['chemical_engineering', 'Chemical engineering'], ['energy', 'Energy'],
  ['computer_science', 'Computer science'], ['medicine', 'Medicine'], ['physics', 'Physics'],
  ['biology', 'Biology'], ['environmental_science', 'Environmental science'],
  ['materials_science', 'Materials science'], ['business', 'Business'],
] as const;

type PromptExample = { question: string; discover: boolean };
const examples = [
  {
    title: 'Find a published source', description: 'Try a question about the PRISMA Statement', icon: Globe2,
    question: 'What does the PRISMA Statement say about reporting systematic reviews? 10.1371/journal.pmed.1000097',
    discover: true,
  },
  {
    title: 'Read a paper closely', description: 'Find the limitations in an uploaded study', icon: FileSearch,
    question: 'What limitations do the authors identify in their study?', discover: false,
  },
  {
    title: 'Compare findings', description: 'Look for agreement across your sources', icon: GitCompareArrows,
    question: 'Where do the studies agree or disagree about their findings?', discover: false,
  },
];

export function ResearchWelcome() {
  return <header className="research-welcome">
    <div className="research-emblem" aria-hidden="true"><Compass size={29} strokeWidth={1.65}/></div>
    <h1>What are you researching?</h1>
    <p>Search the literature, work through your papers, and inspect the evidence behind each finding.</p>
  </header>;
}

export function ResearchExamples({onExample}: {onExample: (example: PromptExample) => void}) {
  return <div className="research-examples" aria-label="Suggested prompts">
    {examples.map(({title, description, icon: Icon, question, discover}) => <button type="button" key={title}
      className="example" onClick={() => onExample({question, discover})}>
      <span className="example-icon"><Icon size={17}/></span>
      <span><strong>{title}</strong><small>{description}</small></span>
      <ArrowUpRight size={15} className="example-arrow" aria-hidden="true"/>
    </button>)}
  </div>;
}

export function ResearchComposer({query, onQuery, discover, onDiscover, busy, onSubmit, onSources}: {
  query: string;
  onQuery: (value: string) => void;
  discover: boolean;
  onDiscover: (value: boolean) => void;
  busy: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onSources: () => void;
}) {
  const form = useRef<HTMLFormElement>(null);
  return <form ref={form} onSubmit={onSubmit} className="research-composer">
    <label className="sr-only" htmlFor="question">Research question</label>
    <textarea id="question" name="question" value={query} onChange={event => onQuery(event.target.value)}
      placeholder="Ask a research question…" required minLength={2} maxLength={1000} rows={2}
      onKeyDown={event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
          event.preventDefault();
          if (!busy && query.trim().length >= 2) form.current?.requestSubmit();
        }
      }}/>
    <div className="composer-toolbar">
      <div className="composer-tools">
        <button type="button" className="tool-button" onClick={onSources} disabled={busy}><Plus size={17}/> Add sources</button>
        <label className={discover ? 'tool-button discovery-tool enabled' : 'tool-button discovery-tool'}>
          <input type="checkbox" name="discover" checked={discover} onChange={event => onDiscover(event.target.checked)}/>
          <Globe2 size={17} aria-hidden="true"/><span>Search literature</span>
        </label>
        <details className="composer-options">
          <summary className="tool-button" aria-label="Research options"><SlidersHorizontal size={16}/> <span>Options</span></summary>
          <div className="composer-popover">
            <label>Research domain<select name="domain">{domains.map(([value, label]) =>
              <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="check"><input type="checkbox" name="model"/> External reranking</label>
            <label className="check"><input type="checkbox" name="synthesis"/> External synthesis</label>
          </div>
        </details>
      </div>
      <button type="submit" className="primary run-button" disabled={busy || query.trim().length < 2}
        aria-label="Run research" title="Run research">
        <ArrowUp size={20} strokeWidth={2.35}/><span>Run research</span>
      </button>
    </div>
  </form>;
}

export function EmptyProject({onCreate}: {onCreate: () => void}) {
  return <div className="card empty">
    <FilePlus2 size={25} aria-hidden="true"/>
    <h2>Create a research project</h2>
    <p>Use a project to keep papers, questions, and reports together.</p>
    <button className="primary" onClick={onCreate}><Plus size={16}/> New project</button>
  </div>;
}
