import {makeScene2D, Rect, Txt} from '@motion-canvas/2d';
import {all, createRef, waitFor} from '@motion-canvas/core';

// Provider-free installation fixture, not a sourced historical assertion.
export default makeScene2D(function* (view) {
  const box = createRef<Rect>();
  const label = createRef<Txt>();
  view.fill('#101827');
  view.add(<Rect ref={box} width={980} height={300} radius={32} fill={'#2563eb'}>
    <Txt ref={label} text={'Before'} fill={'white'} fontSize={90}/>
  </Rect>);
  yield* waitFor(1);
  yield* all(box().scale(1.08, 0.4), label().text('Intervention', 0.4));
  yield* waitFor(1);
  yield* all(box().fill('#087f5b', 0.4), label().text('Consequence', 0.4));
  yield* waitFor(1);
});
