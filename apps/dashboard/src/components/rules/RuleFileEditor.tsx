import { useEffect, useRef, useState } from 'react';
import { messageOf } from '../../lib/message';
import { api } from '../../services/api';
import type { RuleFile } from '../../types/rule';

type Props = { rule: RuleFile; onDirty: (dirty: boolean) => void };
function useRuleContents(id: string) {
  const [content, setContent] = useState('');
  const [original, setOriginal] = useState('');
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api.readRuleFile(id).then(
      (text) => {
        if (active) {
          setContent(text);
          setOriginal(text);
          setLoaded(true);
          setLoading(false);
        }
      },
      (err: Error) => {
        if (active) {
          setError(err.message);
          setLoading(false);
        }
      },
    );
    return () => {
      active = false;
    };
  }, [id]);
  return { content, original, loading, loaded, error, setError, setContent, setOriginal };
}

function useMounted() {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return mounted;
}

function useRuleFile({ rule, onDirty }: Props) {
  const state = useRuleContents(rule.id);
  const [saving, setSaving] = useState(false);
  const mounted = useMounted();
  async function save() {
    setSaving(true);
    state.setError('');
    try {
      await api.saveRuleFile(rule.id, state.content);
      state.setOriginal(state.content);
      if (mounted.current) {
        onDirty(false);
      }
    } catch (err) {
      state.setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }
  function change(text: string) {
    state.setContent(text);
    onDirty(text !== state.original);
  }
  return { ...state, saving, change, save };
}

type State = ReturnType<typeof useRuleFile>;
function EditorHead({ rule, state }: { rule: RuleFile; state: State }) {
  return (
    <div className="skill-panel-heading">
      <div>
        <span className="skill-eyebrow">RULE FILE</span>
        <h2>{rule.name}</h2>
        <p className="note mono">{rule.path}</p>
      </div>
      <button
        type="button"
        className="btn btn-primary"
        disabled={state.loading || state.saving || state.content === state.original}
        onClick={() => void state.save()}
      >
        {state.saving ? 'Saving…' : 'Save changes'}
      </button>
    </div>
  );
}

function EditorBody({ rule, state }: { rule: RuleFile; state: State }) {
  if (state.loading) {
    return <p className="note">Loading file…</p>;
  }
  if (!state.loaded) {
    return null;
  }
  return (
    <textarea
      aria-label={`Edit ${rule.path}`}
      className="skill-editor-text"
      disabled={state.saving}
      value={state.content}
      onChange={(event) => state.change(event.target.value)}
      spellCheck={false}
    />
  );
}

export function RuleFileEditor(props: Props) {
  const state = useRuleFile(props);
  return (
    <div className="skill-editor">
      <EditorHead rule={props.rule} state={state} />
      <p className="note">
        This shared file may also be used by projects and other agents. Changes apply to new runs.
      </p>
      {state.error && (
        <p className="alert" role="alert">
          {state.error}
        </p>
      )}
      <EditorBody rule={props.rule} state={state} />
    </div>
  );
}
