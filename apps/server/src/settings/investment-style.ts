import {z} from 'zod';
import type {InterviewAnswers} from './interview-profile.js';

const styleCodes=['unclear','aggressive','balanced','steady','very_conservative'] as const;
export const styleAssessment=z.object({
 code:z.enum(styleCodes),sources:z.array(z.string()).max(8)
});
type StyleCode=typeof styleCodes[number];
type Risk={grade:number|null;willingness:number|null};
export const styleLabels:Record<StyleCode,string>={
 unclear:'无明确风格',aggressive:'激进型',balanced:'平衡型',steady:'稳健型',very_conservative:'极度保守型'
};

// The model assesses goals and product preferences inside these risk boundaries.
export function eligibleStyles({grade,willingness}:Risk){
 const codes:StyleCode[]=['unclear'];
 if(grade===null||willingness===null)return codes;
 if(grade===5&&willingness>=80)codes.push('aggressive');
 if(grade>=3&&willingness>=40)codes.push('balanced');
 codes.push('steady');
 if(willingness<=20)codes.push('very_conservative');
 return codes;
}

// Older interviews have no model classification. Use only explicit questionnaire evidence.
export function legacyInvestmentStyle(a:InterviewAnswers,risk:Risk):StyleCode{
 const eligible=eligibleStyles(risk),goal=a['01']?.choice,priority=a['09']?.choice,asset=a['92']?.choice;
 if(eligible.includes('very_conservative')&&goal===0&&a['27']?.choice===0&&(asset===2||asset===5))return 'very_conservative';
 if(eligible.includes('aggressive')&&goal===4&&a['27']?.choice===3)return 'aggressive';
 if(eligible.includes('steady')&&goal===0&&priority===0)return 'steady';
 if(eligible.includes('balanced')&&goal===1&&[1,2].includes(a['27']?.choice??-1))return 'balanced';
 return 'unclear';
}
