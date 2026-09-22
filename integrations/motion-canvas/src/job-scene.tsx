import {makeScene2D, Circle, Line, Rect, Txt} from '@motion-canvas/2d';
import {all, createRef, useScene, waitFor} from '@motion-canvas/core';

type Shot = {start: number; end: number; first_frame: string; change: string; last_frame: string};
// An authored before/change/after template, not arbitrary generated JavaScript.
export default makeScene2D(function* (view) {
  const shots = useScene().variables.get<Shot[]>('shots', [])();
  const portrait = useScene().variables.get<boolean>('portrait', true)();
  const width = portrait ? 610 : 500;
  const start = portrait ? [0, -300] : [-330, 0];
  const finish = portrait ? [0, 300] : [330, 0];
  for (const shot of shots) {
    view.removeChildren();
    view.fill('#101827');
    const result = createRef<Rect>();
    const token = createRef<Circle>();
    view.add(<>
      <Rect x={start[0]} y={start[1]} width={width} height={240} radius={20} fill={'#233046'}>
        <Txt text={shot.first_frame} width={width-50} textWrap={true} fontSize={30} fill={'white'} textAlign={'center'}/>
      </Rect>
      <Line points={portrait ? [[0,-140],[0,140]] : [[-60,0],[60,0]]} stroke={'#718096'} lineWidth={6} endArrow/>
      <Rect ref={result} x={finish[0]} y={finish[1]} width={width} height={240} radius={20} fill={'#075e4b'} opacity={0}>
        <Txt text={shot.last_frame} width={width-50} textWrap={true} fontSize={30} fill={'white'} textAlign={'center'}/>
      </Rect>
      <Txt text={shot.change} y={portrait ? -540 : -270} width={portrait?610:1100} textWrap={true} fontSize={32} fill={'#b8dcff'} textAlign={'center'}/>
      <Circle ref={token} x={start[0]} y={start[1]+145} width={38} height={38} fill={'#f4bf58'}/>
    </>);
    const duration = shot.end - shot.start;
    yield* waitFor(duration * 0.2);
    yield* all(result().opacity(1, duration * 0.5), token().position([finish[0],finish[1]+145], duration * 0.5));
    yield* waitFor(duration * 0.3);
  }
});
