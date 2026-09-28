"""Editable original pilot. Missing references deliberately cannot authorize spend."""
from .models import SCHEMA_VERSION


def starter():
    identities={
        "bolt":"Bolt, the approved white-and-teal robot with a rounded black screen-face, cyan eyes and antenna orb. Match the supplied reference exactly.",
        "chick":"A small round yellow storybook chick, orange beak and two tiny feet.",
        "bunny":"A friendly cream storybook bunny with long ears and a round cotton tail.",
        "elephant":"A gentle small gray storybook elephant with a trunk and round ears."}
    refs=[{"id":name+"_ref","uri":"library://"+"0"*32,"sha256":"0"*64,
           "mime_type":"image/png","license":"unresolved","origin":"Upload and review this original character/set reference"}
          for name in [*identities,"backyard"]]
    cast=[{"id":name,"identity":identity,"reference_id":name+"_ref","voice":"cedar",
           "voice_instructions":"Warm, friendly, curious robot guide. Clear short phrases, gentle excitement. No shouting, metallic effect or exaggerated baby talk. Read only the dialogue."}
          for name,identity in identities.items()]
    assets=[{"id":"listen","world_id":"backyard","cast":["bolt"],"mode":"still",
             "prompt":"Bolt listens in the sunny backyard beside a large bush, curious cyan eyes. No hidden animal visible."},
            {"id":"wonder","world_id":"backyard","cast":["bolt"],"mode":"still",
             "prompt":"Close view of Bolt tilting his head, one teal hand raised toward a hidden rustling bush. No animal visible."},
            {"id":"chorus","world_id":"backyard","cast":["bolt"],"mode":"motion","motion_seconds":5,"loopable":True,
             "prompt":"Bolt in the backyard on a clear stage, arms relaxed, ready for a gentle side-to-side dance. No hidden animal visible.",
             "motion_prompt":"Bolt gently sways left and right, waves, returns to his exact starting pose over five seconds. Seamless happy dance loop, stable robot and camera. No new objects or animals."},
            {"id":"parade","world_id":"backyard","cast":list(identities),"mode":"motion","motion_seconds":5,"loopable":True,
             "prompt":"Bolt and exactly three animal friends, chick, bunny and small elephant, in an evenly spaced row in the sunny backyard. Entire bodies and feet visible.",
             "motion_prompt":"A seamless five-second dance loop: chick flaps, bunny makes one gentle hop, elephant steps in place and waves its trunk, Bolt sways. All return to their starting places. Fixed camera, stable anatomy."},
            {"id":"together","world_id":"backyard","cast":list(identities),"mode":"still",
             "prompt":"Bolt and exactly three animal friends chick, bunny and elephant smile together, arranged clearly with each entire body visible. No numbers or text."}]
    for name in ("chick","bunny","elephant"):
        clue={"chick":"A tiny yellow feather beside a bush. No bird visible.",
              "bunny":"Two long ear tips just visible behind a large flowerpot. No full animal visible.",
              "elephant":"A curved gray trunk tip peeks around the open garden gate. No full animal visible."}[name]
        assets.extend([{"id":name+"_clue","world_id":"backyard","cast":["bolt"],"mode":"still",
                       "prompt":"Bolt examines this fair visual clue: "+clue},
                      {"id":name+"_reveal","world_id":"backyard","cast":["bolt",name],
                       "mode":"motion","motion_seconds":10,"loopable":False,
                       "prompt":"Bolt beside the garden bush. The "+name+" is partially visible behind the bush, ready to step out. No other animals.",
                       "motion_prompt":"Complete the reveal within the first three seconds: the "+name+" steps fully out from behind the bush, turns toward Bolt and greets him. Bolt waves. Keep the friend visible and gently animated afterwards; no repeated exit or reset."}])
    beats=[]
    def speech(id,text):return {"id":id,"kind":"speech","character_id":"bolt","text":text}
    def add(id,role,audio,asset,action,*,round_id="",answer="",motion=False,second_asset=None):
        shots=[{"id":id+"_shot","asset_id":asset,"first_state":"Beginning of this beat: "+action,
                "visible_action":action,"last_state":"End of this beat: "+action,"requires_motion":motion}]
        if second_asset:
            shots.append({"id":id+"_close","asset_id":second_asset,"first_state":"Bolt is listening.",
                          "visible_action":"A closer view of Bolt notices the clue.","last_state":"Bolt holds a curious look."})
        beats.append({"id":id,"role":role,"round_id":round_id,"answer":answer,
                      "learning_purpose":"Identify animals from fair clues; participate and repeat their movements.",
                      "audio":audio,"shots":shots})
    add("opening","hook",[speech("opening_vo","Wait! Something is hiding in our garden. I saw a little wiggle behind that bush. Let's look for a clue together!")],
        "listen","Bolt notices the bush and listens with curiosity.",second_asset="wonder")
    add("hook_song","song",[{"id":"hook_first","kind":"song","song_id":"mystery"}],"chorus",
        "Bolt sways and invites us to look for clues.",motion=True)
    questions=[("chick","Look! A yellow feather. This friend has a beak and says cheep. Who is hiding?"),
               ("bunny","Two long ears peek above that pot. This friend can hop. Who is hiding?"),
               ("elephant","Look at that long, bendy trunk by the gate. Which animal is hiding?")]
    reveals=["It's a chick! Hello, little friend. You found our first animal. Can you flap your little wings?",
             "A bunny! Those long ears gave us a clue. Hello, bunny. Let's try one little hop together.",
             "An elephant! Hello, gentle friend. You used every clue. Can you wave your arm like a long trunk?"]
    for i,(name,text) in enumerate(questions):
        add(name+"_question","question",[speech(name+"_question_vo",text),{"id":name+"_wait","kind":"pause","duration_sec":2.5}],
            name+"_clue","The clue remains visible while Bolt waits for the viewer's answer.",round_id=name,answer=name)
        add(name+"_answer","reveal",[speech(name+"_answer_vo",reveals[i])],name+"_reveal",
            "The "+name+" steps out and greets Bolt, completing the reveal.",round_id=name,answer=name,motion=True)
        if i==0:
            add("repeat_hook","song",[{"id":"hook_second","kind":"song","song_id":"mystery"}],"chorus",
                "Bolt repeats the familiar dance and invites another guess.",motion=True)
    add("dance","song",[{"id":"action_song","kind":"song","song_id":"parade"}],"parade",
        "Chick flaps, bunny hops, elephant steps in place and waves its trunk, Bolt sways, all in a repeating dance.",motion=True)
    add("count","recap",[speech("count_vo","A chick, a bunny, and an elephant. One, two, three animal friends! We listened and looked carefully. Everyone is different, and everyone can play together.")],
        "together","Exactly three friends stand beside Bolt, all clearly visible.",second_asset="wonder")
    add("ending","goodbye",[speech("ending_vo","Thank you for exploring with me. Wave goodbye to our friends. See you next time!")],"together",
        "A warm group portrait closes the adventure.")
    return {"schema_version":SCHEMA_VERSION,"project_id":"backyard_hide_and_seek_v1",
            "title":"Bolt, Who Is Hiding in the Backyard?","target_duration_sec":120,
            "learning_goal":"Use visible animal clues to identify three friends and recall their movements.",
            "brand_pack_id":"bolt_kids_original","brand_pack_version":1,"bolt_design":"white_teal_robot",
            "references":refs,"characters":cast,
            "worlds":[{"id":"backyard","description":"The same warm, sunny storybook garden with a playroom doorway, bush, flowerpot and gate. Low clutter; stable layout.","reference_id":"backyard_ref"}],
            "songs":[{"id":"mystery","lyrics":"Who's hiding? Who could it be?\nLook for a clue, come look with me!",
                      "style":"Original gentle preschool acoustic pop, ukulele, bells, clear adult singer, simple melody and immediate vocal entrance.","duration_sec":9},
                     {"id":"parade","lyrics":"Cheep, cheep, flap with me!\nTiny wings, one, two, three!\nHop, hop, bunny feet!\nLittle jumps upon the beat!\nStomp, stomp, nice and slow!\nWave your trunk and off we go!\nThree new friends, hip hip hooray!\nBolt and friends can dance and play!",
                      "style":"Original gentle preschool action song, clear adult singer, light claps, ukulele, short gaps between phrases, simple repetitive melody.","duration_sec":27}],
            "assets":assets,"beats":beats}
