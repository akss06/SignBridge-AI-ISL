import { useRef, useState } from 'react';

interface Props {
  file: File | null;
  onFileSelected: (file: File) => void;
}

export function FileDropZone({ file, onFileSelected }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  return (
    <>
      <label
        className="file-drop"
        style={dragOver ? { borderColor: 'var(--amber)', background: 'rgba(245, 158, 11, 0.06)' } : undefined}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const dropped = e.dataTransfer?.files[0];
          if (dropped) onFileSelected(dropped);
        }}
      >
        <span className="file-drop-icon">⬆</span>
        <span className="file-drop-text">Click or drag a file here</span>
        <input
          ref={inputRef}
          type="file"
          accept=".wav,.mp3,.mp4"
          hidden
          onChange={(e) => {
            const picked = e.target.files?.[0];
            if (picked) onFileSelected(picked);
          }}
        />
      </label>
      <div className="file-name-display">{file ? file.name : 'No file selected'}</div>
    </>
  );
}
