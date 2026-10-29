/**
 * What each value on the symbol drawer's Company tab means, by the label as
 * shown. Written for someone learning to read a company: what the figure is,
 * how it is calculated, and how a trader reads it. Money is in millions of
 * US dollars (M$), as in pm-compdb-cli.
 */
export const COMPANY_HELP: Record<string, string[]> = {
  "Market cap": [
    "Market capitalisation: what the market says the whole company is worth. Share price × number of shares.",
    "Large companies move slowly and trade in size; small ones can swing more. It is the base for P/E and P/S.",
  ],
  "P/E": [
    "Price / earnings: market cap ÷ net income. How many years of the current profit you pay for the company.",
    "High: the market expects growth (or the stock is expensive). Low: cheap, or profits expected to fall. Blank when the company makes a loss, as the ratio has no meaning then.",
  ],
  "P/S": [
    "Price / sales: market cap ÷ revenue. What you pay for each dollar of sales.",
    "Useful for companies with little or no profit yet, where P/E is blank. Margins differ by industry, so compare within one industry.",
  ],
  "Dividend yield": [
    "The yearly dividend as a percentage of the share price. Cash a shareholder is paid for holding the stock.",
    "0% means the company keeps its profit to reinvest, as growth companies often do. A very high yield can warn that the price has fallen or that the dividend is at risk.",
  ],
  "Debt / equity": [
    "Total debt ÷ shareholders' equity. How much the company has borrowed for each dollar its owners have put in.",
    "Above 1 means more debt than equity. High leverage magnifies gains and losses, and interest must be paid in bad years too. Normal levels differ by industry: banks and utilities carry more.",
  ],
  "Credit rating": [
    "A rating agency's view of how likely the company is to repay its debt. AAA is the safest; BBB- and above is 'investment grade'; BB+ and below is 'speculative' (high yield).",
    "A weaker rating means the company pays more to borrow, and a downgrade can push the share price down.",
  ],
  Revenue: [
    "Sales: the money the company took in from customers during the fiscal year, before any costs.",
    "The top line of the income statement. Shown in millions of US dollars (M$).",
  ],
  "Revenue growth": [
    "Revenue this fiscal year compared with the year before, in percent.",
    "Growth is what a high P/E is paying for. Negative means the business shrank.",
  ],
  "Net income": [
    "Profit: what is left of revenue after all costs, interest and taxes. The 'bottom line' and the E in P/E.",
    "Negative means a loss. Shown in M$.",
  ],
  "Net margin": [
    "Net income ÷ revenue, in percent: how many cents of profit each dollar of sales leaves.",
    "Margins are structural: a grocer may live on 2%, a software company on 25%. Compare with competitors, not across industries.",
  ],
  "Operating margin": [
    "Operating profit ÷ revenue, in percent. Profit from running the business, before interest and taxes.",
    "It shows how efficient the core operation is. A big gap to net margin means interest or tax is taking much of the profit.",
  ],
  "Free cash flow": [
    "Cash the business generates after paying for the investments needed to keep it running (equipment, buildings). Shown in M$.",
    "It is real cash, harder to flatter than profit. It is what can pay dividends, buy back shares or repay debt. Growth companies may have it negative while they invest.",
  ],
  "Key market": [
    "The market or customer segment the company earns most of its money in.",
    "It tells you what the company's results depend on: its demand, prices and competition.",
  ],
  "Market position": [
    "Where the company stands against its rivals, for example a leader or a challenger.",
    "Leaders often have pricing power and scale. Challengers can grow faster from a smaller base but carry more risk.",
  ],
  Competitors: [
    "The tickers of the main rivals.",
    "Open one to compare its P/E, margins and growth. A company is judged against its competitors.",
  ],
  "Key risk": [
    "The main thing that could hurt the company's results or share price.",
    "Risk is what separates a cheap stock from a bargain. News about it can move the price sharply.",
  ],
  CEO: [
    "The chief executive, who runs the company day to day, and the year they took over, with years in the role.",
    "A new CEO often means a change of strategy; a long tenure means stability, or an entrenched leader.",
  ],
  "Years in the industry": [
    "How long the CEO has worked in this industry, before and during the current job.",
    "Experience of the industry's cycles counts for something, but is no guarantee of good decisions.",
  ],
  Employees: [
    "The number of people the company employs.",
    "A measure of size and, against revenue, of efficiency: revenue per employee varies greatly between industries.",
  ],
  Founded: [
    "The year the company was started, with its age in years.",
    "Old companies tend to be established and slower-growing; young ones are less proven.",
  ],
  IPO: [
    "Initial public offering: the year the company first sold shares to the public on an exchange, and the value put on it then.",
    "Compare it with today's market cap to see how the company has fared since it listed.",
  ],
  Origin: [
    "How the company began, for example as a start-up, a spin-off or a merger, and by whom.",
    "A company's start often shapes its culture and what it is still best at.",
  ],
};

export const companyHelp = (label: string): string[] | undefined => COMPANY_HELP[label];
