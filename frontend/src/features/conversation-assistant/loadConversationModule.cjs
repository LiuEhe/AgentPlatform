const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')

// Compile the real feature modules while keeping HTTP and lifecycle hooks controlled.
module.exports = function loadConversationModule(name, imports = {}) {
  const cache = new Map()
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const loaded = new Module(filename, module)
    loaded.filename = filename
    loaded.paths = module.paths
    cache.set(filename, loaded)
    loaded.require = id => {
      if (id in imports) return imports[id]
      const local = path.resolve(path.dirname(filename), id + '.ts')
      if (id.startsWith('.') && fs.existsSync(local)) return load(local)
      return require(id)
    }
    loaded._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText, filename)
    return loaded.exports
  }
  return load(path.resolve(__dirname, name))
}
