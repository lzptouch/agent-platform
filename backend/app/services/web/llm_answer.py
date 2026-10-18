import os

import yaml
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import settings


class GPTAnswer:
    TOP_K = 10  # Top K documents to retrieve

    def __init__(self):
        # Load prompt template from a YAML file
        config_path = os.path.join(os.path.dirname(__file__), 'config', 'config.yaml')
        with open(config_path, 'r') as file:
            self.config = yaml.safe_load(file)
        self.model_name = settings.openai_model
        self.api_key = settings.openai_api_key

    def format_reference(self, relevant_docs_list, link_list):
        # Format the references from the retrieved documents for use in the prompt
        top_k = min(self.TOP_K, len(relevant_docs_list))
        reference_url_list = [(relevant_docs_list[i].metadata)['url'] for i in range(top_k)]
        reference_content_list = [relevant_docs_list[i].page_content for i in range(top_k)]
        reference_index_list = [link_list.index(link) + 1 for link in reference_url_list]
        rearranged_index_list = self._rearrange_index(reference_index_list)

        # Create a formatted string of references
        formatted_reference = "\n"
        for i in range(top_k):
            formatted_reference += ('Webpage[' + str(rearranged_index_list[i]) + '], url: ' + reference_url_list[i] + ':\n' + reference_content_list[i] + '\n\n\n')
        return formatted_reference

    def _rearrange_index(self, original_index_list):
        # Rearrange indices to ensure they are unique and sequential
        index_dict = {}
        rearranged_index_list = []
        for index in original_index_list:
            if index not in index_dict:
                index_dict.update({index: len(index_dict) + 1})
                rearranged_index_list.append(len(index_dict))
            else:
                rearranged_index_list.append(index_dict[index])
        return rearranged_index_list

    def get_answer(self, query, relevant_docs, language, output_format, profile):
        # Create an instance of ChatOpenAI and generate an answer
        llm = ChatOpenAI(model=self.model_name, api_key=self.api_key, temperature=0.0)

        template = self.config["template"]
        prompt_template = PromptTemplate(
            input_variables=["profile", "context_str", "language", "query", "format"],
            template=template
        )

        profile = "conscientious researcher" if not profile else profile
        summary_prompt = prompt_template.format(context_str=relevant_docs, language=language, query=query, format=output_format, profile=profile)
        gpt_answer = llm.invoke([HumanMessage(content=summary_prompt)])

        return gpt_answer
