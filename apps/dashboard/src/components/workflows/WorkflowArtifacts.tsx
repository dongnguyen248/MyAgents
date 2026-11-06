import { useState } from 'react';
import type { WorkflowArtifact } from '../../types/workflow';
import { Card } from '../common/Layout';

function ArtifactRow({ artifact }: { artifact: WorkflowArtifact }) {
  const [showContent, setShowContent] = useState(false);
  return (
    <div>
      <p>
        <strong>{artifact.type}</strong>{' '}
        <span className="muted small">
          {artifact.name} · v{artifact.version} · by {artifact.createdBy}
        </span>{' '}
        {artifact.content && (
          <button type="button" className="link" onClick={() => setShowContent((v) => !v)}>
            {showContent ? 'Hide content' : 'View content'}
          </button>
        )}
      </p>
      {showContent && artifact.content && <pre className="artifact-content">{artifact.content}</pre>}
    </div>
  );
}

export function WorkflowArtifacts({ artifacts }: { artifacts?: WorkflowArtifact[] }) {
  if (!artifacts || artifacts.length === 0) {return null;}
  return (
    <Card title="Artifacts">
      <div className="stack">
        {artifacts.map((artifact) => (
          <ArtifactRow key={artifact.id} artifact={artifact} />
        ))}
      </div>
    </Card>
  );
}
