# 此脚本用于修改ipynb文件，添加保存可视化图表的功能
import json
import os

# 确保输出目录存在
if not os.path.exists('visualizations_en'):
    os.makedirs('visualizations_en')
if not os.path.exists('visualizations_cn'):
    os.makedirs('visualizations_cn')

# 处理英文版本的ipynb文件
def process_english_notebook():
    notebook_path = '6111project.ipynb'
    output_path = '6111project_modified.ipynb'
    
    with open(notebook_path, 'r', encoding='utf-8') as f:
        notebook = json.load(f)
    
    # 遍历所有代码单元格
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            source = cell['source']
            
            # 检查是否包含plt.show()，如果有则在其前面添加保存图表的代码
            for i, line in enumerate(source):
                if 'plt.show()' in line:
                    # 查找图表标题以用作文件名
                    title = ''
                    for j in range(max(0, i-15), i):
                        if 'plt.title' in source[j]:
                            try:
                                title = source[j].split("'")[1].split("'")[0].lower().replace(' ', '_')
                            except IndexError:
                                try:
                                    title = source[j].split('"')[1].split('"')[0].lower().replace(' ', '_')
                                except IndexError:
                                    pass
                            break
                    
                    if not title:
                        title = f"figure_{i}"
                    
                    # 在plt.show()前添加保存图表的代码
                    save_code = f"# Save the figure\nplt.savefig('visualizations_en/{title}.png', dpi=300, bbox_inches='tight')\n"
                    source[i] = save_code + source[i]
            
            # 在第一个包含matplotlib的单元格前添加创建目录的代码
            if any('plt.' in line for line in source) and not any('os.makedirs' in line for line in source):
                source.insert(0, "# Create visualizations directory if it doesn't exist\nimport os\nif not os.path.exists('visualizations_en'):\n    os.makedirs('visualizations_en')\n\n")
    
    # 保存修改后的notebook
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=1)
    
    print(f"英文版本处理完成，已保存为 {output_path}")

# 处理中文版本的ipynb文件
def process_chinese_notebook():
    notebook_path = '6111project_中文.ipynb'
    output_path = '6111project_中文_modified.ipynb'
    
    with open(notebook_path, 'r', encoding='utf-8') as f:
        notebook = json.load(f)
    
    # 遍历所有代码单元格
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            source = cell['source']
            
            # 检查是否包含plt.show()，如果有则在其前面添加保存图表的代码
            for i, line in enumerate(source):
                if 'plt.show()' in line:
                    # 查找图表标题以用作文件名
                    title = ''
                    for j in range(max(0, i-15), i):
                        if 'plt.title' in source[j]:
                            try:
                                title = source[j].split("'")[1].split("'")[0].lower().replace(' ', '_')
                            except IndexError:
                                try:
                                    title = source[j].split('"')[1].split('"')[0].lower().replace(' ', '_')
                                except IndexError:
                                    pass
                            break
                    
                    if not title:
                        title = f"figure_{i}"
                    
                    # 在plt.show()前添加保存图表的代码
                    save_code = f"# 保存图表\nplt.savefig('visualizations_cn/{title}.png', dpi=300, bbox_inches='tight')\n"
                    source[i] = save_code + source[i]
            
            # 在第一个包含matplotlib的单元格前添加创建目录的代码
            if any('plt.' in line for line in source) and not any('os.makedirs' in line for line in source):
                source.insert(0, "# 创建可视化输出目录（如果不存在）\nimport os\nif not os.path.exists('visualizations_cn'):\n    os.makedirs('visualizations_cn')\n\n")
    
    # 保存修改后的notebook
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=1)
    
    print(f"中文版本处理完成，已保存为 {output_path}")

# 执行处理
if __name__ == "__main__":
    process_english_notebook()
    process_chinese_notebook()
    print("处理完成！请检查修改后的文件。")