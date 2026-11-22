import content from '../../../../packages/chives-terminal/chives_terminal/workbench-content.json';
import './investor-survey-comparison.css';

export function InvestorSurveyComparison() {
  return <p className="investor-survey">{content.survey.text} <a href={content.survey.url} target="_blank" rel="noreferrer">调查原文</a></p>;
}
