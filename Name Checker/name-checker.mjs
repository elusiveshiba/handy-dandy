#!/usr/bin/env node

/**
 * name-checker - Check if a project name is already taken
 * 
 * Usage: node name-checker.mjs <name> [name2] [name3] ...
 * 
 * Checks GitHub, npm, and PyPI for existing projects with the same name.
 * Handles rate limits automatically with exponential backoff.
 */

const names = process.argv.slice(2);

if (names.length === 0) {
  console.log(`
name-checker - Check project name availability

Usage: node name-checker.mjs <name> [name2] [name3] ...

Examples:
  node name-checker.mjs haunt
  node name-checker.mjs spots pinned stash mapstash
`);
  process.exit(1);
}

// ANSI colors
const c = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
  clearLine: '\x1b[2K\r',
};

function formatNum(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return n.toString();
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function log(msg) {
  process.stdout.write(`${c.clearLine}${msg}`);
}

function logLine(msg) {
  console.log(`${c.clearLine}${msg}`);
}

// Retry wrapper with exponential backoff
async function withRetry(fn, label, maxRetries = 5) {
  let lastError;
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const result = await fn();
      
      // Check for rate limit in result
      if (result?.rateLimited) {
        const waitTime = result.retryAfter || Math.min(60, Math.pow(2, attempt + 2));
        log(`${c.yellow}⏳ ${label}: rate limited, waiting ${waitTime}s...${c.reset}`);
        await sleep(waitTime * 1000);
        continue;
      }
      
      return result;
    } catch (err) {
      lastError = err;
      const waitTime = Math.min(60, Math.pow(2, attempt + 1));
      log(`${c.yellow}⏳ ${label}: error, retrying in ${waitTime}s...${c.reset}`);
      await sleep(waitTime * 1000);
    }
  }
  return { error: lastError?.message || 'Max retries exceeded' };
}

async function checkGitHub(name) {
  return withRetry(async () => {
    const searchUrl = `https://api.github.com/search/repositories?q=${encodeURIComponent(name)}+in:name&sort=stars&order=desc&per_page=10`;
    const res = await fetch(searchUrl, {
      headers: {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'name-checker-cli'
      }
    });
    
    if (res.status === 403 || res.status === 429) {
      const retryAfter = parseInt(res.headers.get('retry-after') || res.headers.get('x-ratelimit-reset'), 10);
      const waitTime = retryAfter ? Math.max(1, retryAfter - Math.floor(Date.now() / 1000)) : null;
      return { rateLimited: true, retryAfter: waitTime };
    }
    
    if (!res.ok) {
      throw new Error(`GitHub API error: ${res.status}`);
    }
    
    const data = await res.json();
    
    // Filter to exact name matches (case-insensitive)
    const exactMatches = data.items.filter(repo => 
      repo.name.toLowerCase() === name.toLowerCase()
    );
    
    const totalStars = exactMatches.reduce((sum, repo) => sum + repo.stargazers_count, 0);
    const topRepo = exactMatches[0];
    
    return {
      platform: 'GitHub',
      count: exactMatches.length,
      totalStars,
      topStars: topRepo?.stargazers_count || 0,
      topRepo: topRepo ? {
        name: topRepo.full_name,
        stars: topRepo.stargazers_count,
        description: topRepo.description?.slice(0, 50) || '',
      } : null
    };
  }, `GitHub/${name}`);
}

async function checkNpm(name) {
  return withRetry(async () => {
    const res = await fetch(`https://registry.npmjs.org/${encodeURIComponent(name.toLowerCase())}`, {
      headers: { 'Accept': 'application/json' }
    });
    
    if (res.status === 404) {
      return { platform: 'npm', available: true };
    }
    
    if (res.status === 429) {
      const retryAfter = parseInt(res.headers.get('retry-after'), 10);
      return { rateLimited: true, retryAfter: retryAfter || null };
    }
    
    if (!res.ok) {
      throw new Error(`npm API error: ${res.status}`);
    }
    
    const data = await res.json();
    
    // Get download counts
    let downloads = 0;
    try {
      const dlRes = await fetch(`https://api.npmjs.org/downloads/point/last-month/${encodeURIComponent(name.toLowerCase())}`);
      if (dlRes.ok) {
        const dlData = await dlRes.json();
        downloads = dlData.downloads || 0;
      }
    } catch {}
    
    return {
      platform: 'npm',
      available: false,
      name: data.name,
      description: data.description?.slice(0, 50) || '',
      downloads,
    };
  }, `npm/${name}`);
}

async function checkPyPI(name) {
  return withRetry(async () => {
    const res = await fetch(`https://pypi.org/pypi/${encodeURIComponent(name)}/json`);
    
    if (res.status === 404) {
      return { platform: 'PyPI', available: true };
    }
    
    if (res.status === 429) {
      const retryAfter = parseInt(res.headers.get('retry-after'), 10);
      return { rateLimited: true, retryAfter: retryAfter || null };
    }
    
    if (!res.ok) {
      throw new Error(`PyPI API error: ${res.status}`);
    }
    
    const data = await res.json();
    
    return {
      platform: 'PyPI',
      available: false,
      name: data.info.name,
      description: data.info.summary?.slice(0, 50) || '',
    };
  }, `PyPI/${name}`);
}

async function checkName(name, index, total) {
  const progress = `[${index + 1}/${total}]`;
  log(`${c.cyan}${progress}${c.reset} Checking ${c.bold}${name}${c.reset}...`);
  
  // Check all platforms in parallel
  const [github, npm, pypi] = await Promise.all([
    checkGitHub(name),
    checkNpm(name),
    checkPyPI(name)
  ]);

  logLine(`${c.cyan}${progress}${c.reset} ${c.bold}${name}${c.reset} ${c.dim}done${c.reset}`);

  return { name, github, npm, pypi };
}

function printTable(results) {
  // Column widths
  const nameW = Math.max(6, ...results.map(r => r.name.length)) + 1;
  const ghReposW = 8;
  const ghStarsW = 10;
  const npmW = 12;
  const pypiW = 8;
  
  const totalW = nameW + ghReposW + ghStarsW + npmW + pypiW + 4;
  
  console.log(`\n${c.bold}${'═'.repeat(totalW)}${c.reset}`);
  console.log(`${c.bold}  RESULTS${c.reset}`);
  console.log(`${c.bold}${'═'.repeat(totalW)}${c.reset}\n`);
  
  // Header
  const header = [
    'Name'.padEnd(nameW),
    'GH Repos'.padEnd(ghReposW),
    'GH Stars'.padEnd(ghStarsW),
    'npm'.padEnd(npmW),
    'PyPI'.padEnd(pypiW),
  ].join(' ');
  
  console.log(`${c.bold}${header}${c.reset}`);
  console.log(`${c.dim}${'─'.repeat(totalW)}${c.reset}`);
  
  // Rows
  for (const r of results) {
    const ghRepos = r.github.error ? '?' : r.github.count.toString();
    const ghStars = r.github.error ? '?' : formatNum(r.github.totalStars);
    
    let npmStatus, npmColor;
    if (r.npm.error) {
      npmStatus = '?';
      npmColor = c.yellow;
    } else if (r.npm.available) {
      npmStatus = '✓ free';
      npmColor = c.green;
    } else {
      npmStatus = `✗ ${formatNum(r.npm.downloads)}/mo`;
      npmColor = c.red;
    }
    
    let pypiStatus, pypiColor;
    if (r.pypi.error) {
      pypiStatus = '?';
      pypiColor = c.yellow;
    } else if (r.pypi.available) {
      pypiStatus = '✓ free';
      pypiColor = c.green;
    } else {
      pypiStatus = '✗ taken';
      pypiColor = c.red;
    }
    
    const row = [
      r.name.padEnd(nameW),
      ghRepos.padEnd(ghReposW),
      ghStars.padEnd(ghStarsW),
      `${npmColor}${npmStatus.padEnd(npmW)}${c.reset}`,
      `${pypiColor}${pypiStatus.padEnd(pypiW)}${c.reset}`,
    ].join(' ');
    
    console.log(row);
  }
  
  console.log(`${c.dim}${'─'.repeat(totalW)}${c.reset}`);
  
  // Best candidates
  const available = results.filter(r => 
    !r.npm.error && r.npm.available && 
    !r.pypi.error && r.pypi.available &&
    !r.github.error && r.github.count <= 5
  );
  
  if (available.length > 0) {
    console.log(`\n${c.green}${c.bold}✓ Best candidates:${c.reset} ${available.map(r => r.name).join(', ')}`);
  }
  
  // Detailed GitHub info for notable repos
  const notable = results.filter(r => r.github.topRepo && r.github.topStars >= 100);
  if (notable.length > 0) {
    console.log(`\n${c.bold}Notable GitHub conflicts:${c.reset}`);
    for (const r of notable) {
      const repo = r.github.topRepo;
      console.log(`  ${c.yellow}${r.name}${c.reset}: ${repo.name} (${formatNum(repo.stars)}★)`);
      if (repo.description) {
        console.log(`    ${c.dim}${repo.description}${c.reset}`);
      }
    }
  }
  
  console.log('');
}

async function main() {
  console.log(`\n${c.bold}${c.blue}name-checker${c.reset} - Checking ${names.length} name${names.length > 1 ? 's' : ''}...\n`);
  
  const results = [];
  
  for (let i = 0; i < names.length; i++) {
    const result = await checkName(names[i], i, names.length);
    results.push(result);
    
    // Small delay between checks to be nice to APIs
    if (i < names.length - 1) {
      await sleep(300);
    }
  }
  
  printTable(results);
}

main().catch(err => {
  console.error(`${c.red}Error: ${err.message}${c.reset}`);
  process.exit(1);
});
