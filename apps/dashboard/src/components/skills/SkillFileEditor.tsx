import { useEffect, useState } from 'react';
import { api } from '../../services/api';

type Props = { id: string; path: string; onDirty: (dirty: boolean) => void; onSaved: () => void };

function useFileContents(id: string, path: string) {
  const [content, setContent] = useState('');
  const [original, setOriginal] = useState('');
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api.readSkillFile(id, path).then(
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
  }, [id, path]);
  return { content, setContent, original, setOriginal, loading, loaded, error, setError };
}

function useFile(props: Props) {
  const state = useFileContents(props.id, props.path);
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    state.setError('');
    try {
      await api.saveSkillFile(props.id, props.path, state.content);
      state.setOriginal(state.content);
      props.onDirty(false);
      props.onSaved();
    } catch (err) {
      state.setError(err instanceof Error ? err.message : 'Could not save file');
    } finally {
      setSaving(false);
    }
  }
  function change(text: string) {
    state.setContent(text);
    props.onDirty(text !== state.original);
  }
  return { ...state, saving, save, change };
}

type FileState = ReturnType<typeof useFile>;

function EditorHeader({ id, path, file }: { id: string; path: string; file: FileState }) {
  return (
    <div className="skill-panel-heading">
      <div>
        <span className="skill-eyebrow">FILE EDITOR</span>
        <h2>{path}</h2>
        <p className="note">
          skills/{id}/{path}
        </p>
      </div>
      <button
        className="btn btn-primary"
        type="button"
        disabled={file.loading || file.saving || file.content === file.original}
        onClick={file.save}
      >
        {file.saving ? 'Saving…' : 'Save changes'}
      </button>
    </div>
  );
}

function EditorBody({ path, file }: { path: string; file: FileState }) {
  if (file.loading) {
    return <p className="note">Loading file…</p>;
  }
  if (!file.loaded) {
    return null;
  }
  return (
    <textarea
      disabled={file.saving}
      aria-label={`Edit ${path}`}
      className="skill-editor-text"
      value={file.content}
      onChange={(event) => file.change(event.target.value)}
      spellCheck={false}
    />
  );
}

export function SkillFileEditor(props: Props) {
  const file = useFile(props);
  return (
    <div className="skill-editor">
      <EditorHeader id={props.id} path={props.path} file={file} />
      {file.error && (
        <p className="alert" role="alert">
          {file.error}
        </p>
      )}
      <EditorBody path={props.path} file={file} />
      <p className="note">
        Changes to SKILL.md affect future runs when this skill is enabled and mapped to an agent.
      </p>
    </div>
  );
}
