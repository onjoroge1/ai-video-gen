import {Renderer, RendererResult, Vector2} from '@motion-canvas/core';
// The Vite project loader builds the real project metadata and exporter registry.
// @ts-expect-error Motion Canvas's project loader does not declare this query type.
import project from './job-project.ts?project';

declare global {interface Window {renderEngineJob: (data: {shots: unknown[]; portrait: boolean; frames: number}) => Promise<void>}}
window.renderEngineJob = async data => {
  project.variables = {shots: data.shots, portrait: data.portrait};
  const renderer = new Renderer(project);
  let result: RendererResult | undefined;
  renderer.onFinished.subscribe(value => {result = value;});
  await renderer.render({
    ...project.meta.getFullRenderingSettings(),
    name: 'job', range: [0, (data.frames - 1) / 24], fps: 24,
    size: data.portrait ? new Vector2(720,1280) : new Vector2(1280,720), resolutionScale: 1,
    exporter: {name: '@motion-canvas/core/image-sequence', options: {fileType:'image/png',quality:100,groupByScene:false}},
  });
  if (result !== RendererResult.Success) throw new Error('Motion Canvas failed to export the requested frame range');
};
