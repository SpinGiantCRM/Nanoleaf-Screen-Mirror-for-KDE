'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {selectArtifacts, cleanup} = require('./cleanup_artifacts.cjs');
const now = Date.parse('2026-10-14T00:00:00Z');
const artifact = (id, created_at, branch = 'main', name = 'native') =>
  ({id, created_at, name, expired: false, workflow_run: {head_branch: branch}});

test('protects fresh, latest main/open-PR downloads and unknown dates', () => {
  const items = [artifact(1, '2026-09-01'), artifact(2, '2026-09-02'),
    artifact(3, '2026-09-01', 'open'), artifact(4, '2026-10-13', 'closed'),
    artifact(5, 'bad date', 'closed'), artifact(6, '2026-09-01', 'closed'),
    {...artifact(7, '2026-09-01', 'closed'), expired: true},
    artifact(8, '2026-09-01', 'main', 'other-download')];
  assert.deepEqual(selectArtifacts(items, ['main', 'open'], now).map(a => a.id), [1, 6]);
  assert.deepEqual(selectArtifacts(items.reverse(), ['main', 'open'], now).map(a => a.id), [6, 1]);
  assert.throws(() => selectArtifacts(items, [], NaN));
});

test('dry run never deletes; cleanup paginates and only touches artifact IDs', async () => {
  const deleted = [];
  const artifacts = [artifact(1, '2000-01-01'), artifact(2, '2001-01-01'),
    artifact(3, '2000-01-01', 'same-repo'), artifact(4, '2000-01-01', 'fork-name')];
  const pulls = [{head: {ref: 'same-repo', repo: {id: 1}}},
    {head: {ref: 'fork-name', repo: {id: 2}}}];
  const github = {rest: {repos: {get: async () => ({data: {id: 1, default_branch: 'main'}})},
    pulls: {list: 'pulls'}, actions: {listArtifactsForRepo: 'artifacts',
      deleteArtifact: async args => deleted.push(args.artifact_id)}},
    paginate: async endpoint => endpoint === 'pulls' ? pulls : artifacts};
  const args = {github, context: {repo: {owner: 'test', repo: 'test'}}, core: {info() {}}};
  await cleanup(args);
  assert.deepEqual(deleted, []);
  await cleanup({...args, dryRun: false});
  assert.deepEqual(deleted, [1, 4]);
});
