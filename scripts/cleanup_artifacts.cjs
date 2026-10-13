'use strict';

// Only old, unprotected artifacts are candidates. Release assets/tags are never
// queried or deleted. Invalid timestamps fail closed rather than deleting data.
function selectArtifacts(artifacts, activeBranches, now = Date.now(), days = 30) {
  if (!Number.isFinite(now) || !Number.isFinite(days) || days < 1) {
    throw new Error('Invalid artifact retention window');
  }
  const active = new Set(activeBranches);
  const latest = new Map();
  for (const artifact of artifacts) {
    const branch = artifact.workflow_run?.head_branch;
    const time = Date.parse(artifact.created_at);
    if (artifact.expired || !active.has(branch) || !Number.isFinite(time)) continue;
    const key = `${artifact.name}\0${branch}`;
    const previous = latest.get(key);
    if (!previous || time > Date.parse(previous.created_at)) latest.set(key, artifact);
  }
  const protectedIds = new Set([...latest.values()].map(a => a.id));
  const cutoff = now - days * 86400000;
  return artifacts.filter(a => !a.expired && !protectedIds.has(a.id)
    && Number.isFinite(Date.parse(a.created_at)) && Date.parse(a.created_at) < cutoff);
}

async function cleanup({github, context, core, dryRun = true}) {
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  const metadata = await github.rest.repos.get(repo);
  const pulls = await github.paginate(github.rest.pulls.list, {...repo, state: 'open', per_page: 100});
  const activeBranches = [metadata.data.default_branch, ...pulls
    .filter(p => p.head.repo?.id === metadata.data.id).map(p => p.head.ref)];
  const artifacts = await github.paginate(github.rest.actions.listArtifactsForRepo, {...repo, per_page: 100});
  const candidates = selectArtifacts(artifacts, activeBranches);
  for (const artifact of candidates) {
    core.info(`${dryRun ? 'Would delete' : 'Deleting'} old artifact ${artifact.id} (${artifact.name})`);
    if (!dryRun) await github.rest.actions.deleteArtifact({...repo, artifact_id: artifact.id});
  }
  core.info(`${candidates.length} old candidates; newest downloads for main/open PRs and all artifacts under 30 days retained.`);
}
module.exports = {selectArtifacts, cleanup};
