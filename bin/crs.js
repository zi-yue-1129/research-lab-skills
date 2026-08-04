#!/usr/bin/env node
'use strict';

const path = require('path');
const fs   = require('fs');
const os   = require('os');

// ── constants ─────────────────────────────────────────────────────────────────

const VERSION    = require('../package.json').version;
const PKG_SKILLS = path.join(__dirname, '..', 'skills');

// Shared foundation both lab and ARS skills depend on — always installed
const RESOLVER_SKILLS = ['resource-resolver'];
const LAB_SKILLS = ['research-log', 'report-slides', 'research-mode'];
const ARS_SKILLS = ['deep-research', 'academic-paper', 'academic-paper-reviewer', 'academic-pipeline'];
const ALL_SKILLS = [...RESOLVER_SKILLS, ...LAB_SKILLS, ...ARS_SKILLS];

// AI target → skills root path
const AI_PATHS = {
  claude:   path.join(os.homedir(), '.claude',  'skills'),
  cursor:   path.join(os.homedir(), '.cursor',  'skills'),
  windsurf: path.join(os.homedir(), '.windsurf','skills'),
  copilot:  path.join(os.homedir(), '.github',  'copilot-skills'),
};

// ── helpers ───────────────────────────────────────────────────────────────────

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function log(msg)  { process.stdout.write(msg + '\n'); }
function warn(msg) { process.stderr.write('Warning: ' + msg + '\n'); }
function die(msg)  { process.stderr.write('Error: ' + msg + '\n'); process.exit(1); }

function parseArgs(args) {
  const flags = {
    global:  args.includes('--global'),
    labOnly: args.includes('--lab-only'),
    arsOnly: args.includes('--ars-only'),
    ai:      'claude',
  };
  if (flags.labOnly && flags.arsOnly) die('--lab-only and --ars-only cannot be combined.');

  const aiFlag = args.find(a => a.startsWith('--ai=') || a === '--ai');
  if (aiFlag) {
    const val = aiFlag.includes('=')
      ? aiFlag.split('=')[1]
      : args[args.indexOf(aiFlag) + 1];
    if (val) flags.ai = val.toLowerCase();
  }
  return flags;
}

function selectSkills(flags) {
  if (flags.labOnly) return [...RESOLVER_SKILLS, ...LAB_SKILLS];
  if (flags.arsOnly) return [...RESOLVER_SKILLS, ...ARS_SKILLS];
  return ALL_SKILLS;
}

// resource-resolver is a shared dependency of both skill families. A subset
// uninstall (--lab-only / --ars-only) must not pull it out from under the
// skills that stay installed; only a full uninstall removes it.
function selectSkillsForUninstall(flags) {
  if (flags.labOnly) return LAB_SKILLS;
  if (flags.arsOnly) return ARS_SKILLS;
  return ALL_SKILLS;
}

function resolveTarget(flags) {
  if (!flags.global) {
    const localBase = flags.ai === 'claude'
      ? path.join(process.cwd(), '.claude', 'skills')
      : path.join(process.cwd(), `.${flags.ai}`, 'skills');
    return localBase;
  }
  if (!(flags.ai in AI_PATHS)) {
    die(`Unknown AI target: ${flags.ai}\nSupported: ${Object.keys(AI_PATHS).join(', ')}`);
  }
  return AI_PATHS[flags.ai];
}

// ── commands ──────────────────────────────────────────────────────────────────

function cmdInit(args) {
  const flags  = parseArgs(args);
  const skills = selectSkills(flags);
  const target = resolveTarget(flags);
  const scope  = flags.labOnly ? 'lab' : flags.arsOnly ? 'ars' : 'all';

  log(`Installing research-lab-skills v${VERSION} (${scope})`);
  log(`Target (${flags.global ? 'global' : 'project'}): ${target}`);
  log('');

  for (const skill of skills) {
    const src  = path.join(PKG_SKILLS, skill);
    const dest = path.join(target, skill);
    if (!fs.existsSync(src)) { warn(`Skill source not found: ${src} (skipped)`); continue; }
    copyDir(src, dest);
    log(`  ✓ ${skill}`);
  }

  log('');
  log(`Installed ${skills.length} skill(s) to: ${target}`);
  log('Restart Claude Code to activate.');
  if (!flags.arsOnly)  log('  Lab:      /research-log  /report-slides  /mode');
  if (!flags.labOnly)  log('  Academic: /ars-full  /ars-plan  /ars-lit-review  /ars-review  and more');
}

function cmdUninstall(args) {
  const flags  = parseArgs(args);
  const skills = selectSkillsForUninstall(flags);
  const target = resolveTarget(flags);

  log(`Uninstalling from: ${target}`);
  for (const skill of skills) {
    const dest = path.join(target, skill);
    if (fs.existsSync(dest)) {
      fs.rmSync(dest, { recursive: true, force: true });
      log(`  ✓ Removed: ${dest}`);
    } else {
      log(`  - Not found (skipped): ${dest}`);
    }
  }
  log('Done.');
}

function cmdUpdate(args) {
  log('Updating skills (reinstalling from current package)...');
  log('');
  cmdInit(args);
}

function cmdVersions() {
  log(`research-lab-skills v${VERSION}`);
  log('To update: npm update -g research-lab-skills');
}

function cmdHelp() {
  log(`
research-lab-skills (crs) v${VERSION}

8 Claude Code skills for research teams:
  Lab:      /research-log  /report-slides  /mode
  Academic: /ars-full  /ars-plan  /ars-lit-review  /ars-review  and more
  Shared:   resource-resolver (always installed; other skills depend on it)

Quick install (no global npm needed):
  npx research-lab-skills init --global

Or install globally then use crs:
  npm install -g research-lab-skills
  crs init --global

Usage:
  crs init                        Install all 8 skills (project-local)
  crs init --global               Install all 8 skills globally
  crs init --lab-only             Install lab skills + resource-resolver (research-log, report-slides, research-mode)
  crs init --ars-only             Install ARS skills + resource-resolver (deep-research, academic-paper, ...)
  crs init --ai cursor            Install for Cursor (project-local)
  crs init --ai claude --global   Install globally for Claude Code

  crs update [--global] [--lab-only|--ars-only]    Reinstall from this package version
  crs uninstall [--global] [--lab-only|--ars-only]  Remove installed skills

  crs versions                    Show installed version
  crs help                        Show this help

Supported AI targets: ${Object.keys(AI_PATHS).join(', ')}

After install, restart your AI assistant.
`.trim());
}

// ── main ──────────────────────────────────────────────────────────────────────

const [,, cmd, ...rest] = process.argv;

switch (cmd) {
  case 'init':      cmdInit(rest);      break;
  case 'update':    cmdUpdate(rest);    break;
  case 'uninstall': cmdUninstall(rest); break;
  case 'versions':  cmdVersions();      break;
  case 'help':
  case '--help':
  case '-h':        cmdHelp();          break;
  case undefined:   cmdHelp();          break;
  default: die(`Unknown command: ${cmd}\nRun "crs help" for usage.`);
}
