const test = require('node:test')
const assert = require('node:assert/strict')
const { mount, find, text, flush, vue } = require('./componentTestHarness.cjs')

function setup(decode, encode = callback => callback(new Blob(['encoded pixels'], { type: 'image/png' }))) {
  const previous = global.createImageBitmap, draws = [], results = [], cancellations = []
  global.createImageBitmap = decode
  const props = vue.reactive({ file: new File(['x'], 'a.png'), onConfirm: file => results.push(file), onCancel: () => cancellations.push(true) })
  const f = mount('AvatarCropper.vue', {}, props, tag => tag === 'canvas' ? {
    getContext: () => ({ clearRect() {}, drawImage: (...args) => draws.push(args.slice(1)) }),
    getBoundingClientRect: () => ({ width: 256 }), setPointerCapture() {}, releasePointerCapture() {},
    toBlob: encode,
  } : {})
  return { ...f, props, draws, results, cancellations, dispose() { f.app.unmount(); global.createImageBitmap = previous } }
}

test('crop centers landscape, zooms, clamps dragging and exports a png only on confirmation', async () => {
  let closed = 0
  const f = setup(async () => ({ width: 800, height: 400, close() { closed++ } }))
  try {
    await flush()
    assert.deepEqual(f.draws.at(-1), [200, 0, 400, 400, 0, 0, 512, 512])
    const slider = find(f.root, n => n.type === 'range')
    slider.value = '2'; slider.listeners.input({ target: slider }); await flush()
    assert.deepEqual(f.draws.at(-1), [300, 100, 200, 200, 0, 0, 512, 512])
    const canvas = find(f.root, n => n.tag === 'canvas')
    canvas.onPointerdown({ pointerId: 1, clientX: 0, clientY: 0 })
    canvas.onPointermove({ pointerId: 1, clientX: 10000, clientY: 10000 }); await flush()
    assert.deepEqual(f.draws.at(-1), [0, 0, 200, 200, 0, 0, 512, 512])
    assert.equal(f.results.length, 0)
    await find(f.root, n => n.id === 'avatar-crop-confirm').onClick(); await flush()
    assert.equal(f.results[0].type, 'image/png')
    assert.equal(f.results[0].name, 'avatar.png')
  } finally { f.dispose(); assert.equal(closed, 1) }
})

test('late decoded bitmap is closed after cropper unmount without confirmation', async () => {
  let release, closed = 0
  const f = setup(() => new Promise(resolve => { release = resolve }))
  f.dispose()
  release({ width: 400, height: 800, close() { closed++ } }); await flush()
  assert.equal(closed, 1)
  assert.equal(f.results.length, 0)
})

test('broken image shows an error and does not allow confirming an empty canvas', async () => {
  const f = setup(async () => { throw Error('bad bytes') })
  try {
    await flush()
    assert.match(text(f.root), /图片/)
    assert.equal(find(f.root, n => n.id === 'avatar-crop-confirm').disabled, true)
    assert.equal(f.results.length, 0)
  } finally { f.dispose() }
})

test('Esc during delayed export cancels selection and late export cannot confirm after unmount', async () => {
  let finishExport
  const f = setup(async () => ({ width: 400, height: 400, close() {} }), callback => { finishExport = callback })
  await flush()
  const pending = find(f.root, n => n.id === 'avatar-crop-confirm').onClick()
  find(f.root, n => n.tag === 'dialog').onCancel({ preventDefault() {} })
  const cancellations = f.cancellations.length
  f.dispose()
  finishExport(new Blob(['late pixels'], { type: 'image/png' })); await pending; await flush()
  assert.equal(cancellations, 1)
  assert.equal(f.results.length, 0)
})
