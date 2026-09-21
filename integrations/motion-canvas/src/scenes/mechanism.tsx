import {makeScene2D, Circle, Line, Rect, Txt} from '@motion-canvas/2d';
import {all, createRef, waitFor} from '@motion-canvas/core';

// A fictional causal-mechanism fixture. Copy into a named scene and replace
// labels/timing with reviewed storyboard data; never invent numeric evidence.
export default makeScene2D(function* (view) {
  const token = createRef<Circle>();
  const reward = createRef<Rect>();
  const result = createRef<Rect>();
  const state = createRef<Txt>();
  view.fill('#101827');
  view.add(<>
    <Txt text={'An incentive changes a choice'} y={-380} fill={'white'} fontSize={58}/>
    <Txt text={'ILLUSTRATIVE TEMPLATE · NOT HISTORICAL DATA'} y={-300} fill={'#9ca3af'} fontSize={24}/>
    <Rect x={-430} width={400} height={180} radius={24} fill={'#233046'}>
      <Txt text={'Option A'} fill={'white'} fontSize={48}/>
    </Rect>
    <Rect x={430} width={400} height={180} radius={24} fill={'#233046'}>
      <Txt text={'Option B'} fill={'white'} fontSize={48}/>
    </Rect>
    <Line points={[[-180, 0], [180, 0]]} stroke={'#718096'} lineWidth={8} endArrow/>
    <Rect ref={reward} x={430} y={-170} width={300} height={80} radius={16} fill={'#d69e2e'} opacity={0}>
      <Txt text={'Reward'} fill={'#101827'} fontSize={36}/>
    </Rect>
    <Circle ref={token} x={-430} y={130} width={70} height={70} fill={'#60a5fa'}/>
    <Rect ref={result} y={300} width={680} height={130} radius={24} fill={'#233046'}>
      <Txt ref={state} text={'Before: choice A'} fill={'white'} fontSize={42}/>
    </Rect>
  </>);
  yield* waitFor(1);
  yield* reward().opacity(1, 0.5);
  yield* state().text('Intervention: reward B', 0.4);
  yield* token().position([430, 130], 1.2);
  yield* waitFor(0.9);
  yield* token().position([0, 220], 1);
  yield* all(result().fill('#075e4b', 0.5), state().text('Consequence: choice B', 0.5));
  yield* waitFor(2.5);
});
