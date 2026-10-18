import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');
const backendDir = path.join(rootDir, 'backend');

const isWindows = process.platform === 'win32';

// Look for virtualenvs in backend/.venv or .venv
const candidateVenvDirs = [
  path.join(backendDir, '.venv'),
  path.join(rootDir, '.venv'),
];

function findVenvBinary(binaryName) {
  const exeName = isWindows ? `${binaryName}.exe` : binaryName;
  for (const venvDir of candidateVenvDirs) {
    const scriptsDir = isWindows
      ? path.join(venvDir, 'Scripts')
      : path.join(venvDir, 'bin');
    const fullPath = path.join(scriptsDir, exeName);
    if (existsSync(fullPath)) {
      return fullPath;
    }
  }
  return null;
}

const action = process.argv[2];
let command = '';
let args = [];

if (action === 'seed') {
  const pythonBin = findVenvBinary('python') || (isWindows ? 'python' : 'python3');
  command = pythonBin;
  const userArgs = process.argv.slice(3);
  args = ['-m', 'app.seed_db', ...userArgs];
} else if (action === 'test') {
  const pytestBin = findVenvBinary('pytest');
  if (pytestBin) {
    command = pytestBin;
    args = process.argv.slice(3);
  } else {
    const pythonBin = findVenvBinary('python') || (isWindows ? 'python' : 'python3');
    command = pythonBin;
    args = ['-m', 'pytest', ...process.argv.slice(3)];
  }
} else {
  // Default: start uvicorn server
  const userArgs = action && action !== 'start' ? process.argv.slice(2) : process.argv.slice(3);
  const uvicornBin = findVenvBinary('uvicorn');
  if (uvicornBin) {
    command = uvicornBin;
    args = ['app.main:app', '--app-dir', 'backend', '--port', '8000', '--reload', ...userArgs];
  } else {
    const pythonBin = findVenvBinary('python') || (isWindows ? 'python' : 'python3');
    command = pythonBin;
    args = ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--port', '8000', '--reload', ...userArgs];
  }
}

// Ensure backend is in PYTHONPATH
const existingPythonPath = process.env.PYTHONPATH || '';
const newPythonPath = existingPythonPath
  ? `${backendDir}${path.delimiter}${existingPythonPath}`
  : backendDir;

const env = {
  ...process.env,
  PYTHONPATH: newPythonPath,
};

const child = spawn(command, args, {
  cwd: rootDir,
  env,
  stdio: 'inherit',
  shell: false,
});

child.on('error', (err) => {
  if (err.code === 'ENOENT') {
    console.error(`\n[ProofSettle] Error: Could not find executable: ${command}`);
    console.error('[ProofSettle] Make sure the backend virtual environment is installed:');
    console.error('  cd backend');
    console.error(isWindows ? '  python -m venv .venv && .\\.venv\\Scripts\\pip install -e .' : '  python3 -m venv .venv && ./.venv/bin/pip install -e .');
    console.error('  (or run: uv sync)\n');
  } else {
    console.error(`\n[ProofSettle] Failed to start backend: ${err.message}\n`);
  }
  process.exit(1);
});

child.on('close', (code) => {
  process.exit(code ?? 0);
});

process.on('SIGINT', () => {
  child.kill('SIGINT');
});

process.on('SIGTERM', () => {
  child.kill('SIGTERM');
});
